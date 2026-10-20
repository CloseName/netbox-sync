"""Source onboarding routes and their registration continuation lifecycle."""

from uuid import UUID
from fastapi import Request
from ..application.observability import ErrorCode
from ..application.onboarding import OnboardingError
from ..application.sources import source_view
from ..auth_policy import AuthError
from ..host_registration import HostRegistrationConflict
from .auth import COOKIE
from .catalog import CatalogError
from .dto import SourceDTO
from .lifecycle_client import LifecycleRequestError
from .onboarding_dto import (
    ConnectionRequest,
    ConnectionResult,
    RegistrationRequest,
    RegistrationStatusRequest,
    PlacementResolutionRequest,
    CancellationRequest,
    CancellationResult,
)


def install_onboarding_routes(
    app,
    router,
    *,
    settings,
    onboarding_service,
    onboarding_injected,
    auth_client,
    lifecycle_client,
    catalog_validate,
    LOGGER,
):
    """Preserve registration ordering, receipt guards and continuation ownership."""
    from .onboarding_dto import DestinationRequest

    @router.post("/sources/check-destination")
    def check_destination(payload: DestinationRequest, http: Request):
        from ..application.onboarding import PendingCredentials
        from ..probe_worker import remote_test_authorized

        session = http.cookies.get(COOKIE)
        policy = auth_client.call("probe.policy", session=session)
        if not settings.probe_socket:
            raise AuthError("AUTH_UNAVAILABLE")
        remote_test_authorized(
            settings.probe_socket,
            PendingCredentials(payload.source_type, payload.address, True, "", "", "", port=payload.port),
            session,
            policy["revision"],
            destination_only=True,
        )
        return {"allowed": True}

    @router.post("/sources/test-connection", response_model=ConnectionResult)
    def connection_test(request: ConnectionRequest, http: Request):
        session = http.cookies.get(COOKIE)
        policy = auth_client.call("probe.policy", session=session)
        from ..probe_worker import remote_test_authorized

        preview = None
        recovery_meta = None
        if request.recovery_source:
            auth_client.call("authorize", session=session, permission="source.remove")
            if request.source_type != "esxi":
                raise LifecycleRequestError("SOURCE_RECOVERY_IDENTITY_REVIEW")
            recovery_meta = lifecycle_client.recovery(
                "describe", request.recovery_source, actor_id=http.state.principal["principal_id"]
            )
        if settings.probe_socket:
            preview = remote_test_authorized(
                settings.probe_socket,
                request.credentials(),
                session,
                policy["revision"],
                **(
                    {"preview": True}
                    if request.preview or request.registration_resume or request.source_type == "esxi"
                    else {}
                ),
            )
            if request.registration_resume:
                saved = (
                    jobs.get(
                        request.registration_resume.source_instance,
                        request.registration_resume.registration_id,
                        http.state.principal["principal_id"],
                    )
                    if jobs
                    else None
                )
                # RegistrationJobs.get returns a database mapping; guarded by saved above.
                # pylint: disable-next=unsubscriptable-object
                if saved and saved["state"] == "STAGING":
                    checked = jobs.resume_staging(
                        request.registration_resume.source_instance,
                        request.registration_resume.registration_id,
                        http.state.principal["principal_id"],
                        request.credentials(),
                        preview,
                    )
                    token = onboarding_service._pending.issue(request.credentials(), checked)
                else:
                    token = onboarding_service.accept_registration_resume(
                        request.credentials(),
                        preview,
                        request.registration_resume.source_instance,
                        request.registration_resume.registration_id,
                        http.state.principal["principal_id"],
                    )
            else:
                token = (
                    onboarding_service.accept_recovery_credentials(
                        request.credentials(), preview, request.recovery_source, recovery_meta["host_uuid"]
                    )
                    if recovery_meta
                    else onboarding_service.accept_checked_credentials(request.credentials(), preview)
                )
        elif onboarding_injected and not request.recovery_source and not request.registration_resume:
            token = onboarding_service.test_connection(request.credentials())
        else:
            # Explicit in-process adapter injection is only for tests. Production
            # has a required remote probe; no API egress fallback.
            raise AuthError("AUTH_UNAVAILABLE")
        try:
            auth_client.call(
                "receipt.issue",
                session=session,
                receipt=token,
                destination=request.address,
                provider=request.source_type,
                revision=policy["revision"],
            )
        except AuthError:
            onboarding_service.cancel(token)
            raise
        from ..registration_namespace import new_source

        return ConnectionResult(
            onboarding_token=token,
            preview=preview,
            suggested_source_instance=(
                request.registration_resume.source_instance
                if request.registration_resume
                else new_source(request.source_type, settings.source_namespace)
            ),
        )

    from .onboarding_dto import PlacementReviewRequest

    @router.post("/sources/review-placement")
    def review_placement(payload: PlacementReviewRequest, http: Request):
        auth_client.call("receipt.check", session=http.cookies.get(COOKIE), receipt=payload.onboarding_token)
        catalog_validate(
            settings.bootstrap_socket,
            payload.references,
            payload.host_types,
            onboarding_service.preview(payload.onboarding_token),
            pending_cluster=payload.create_cluster,
        )
        return {"valid": True}

    @router.post("/sources/resolve-placement")
    def resolve_placement(payload: PlacementResolutionRequest, http: Request):
        from .catalog import call

        auth_client.call("receipt.check", session=http.cookies.get(COOKIE), receipt=payload.onboarding_token)
        preview = onboarding_service.preview(payload.onboarding_token)
        if not preview:
            raise CatalogError("SELECTION_REQUIRED")
        if payload.prepare:
            auth_client.call("authorize", session=http.cookies.get(COOKIE), permission="catalog.create", audit=True)
        resolved = call(
            settings.bootstrap_socket,
            dict(
                action="resolve-placement",
                provider=preview["provider"],
                hosts=preview["hosts"],
                name=payload.name,
                site_id=payload.site_id,
                default_site_slug=settings.default_site_slug,
                host_types=payload.host_types,
            ),
            prepare=payload.prepare,
        )
        site = resolved.get("references", {}).get("site", {})
        if site.get("slug"):
            onboarding_service.check_placement(site["slug"], payload.name)
        return resolved

    def complete_registration(
        request, onboarding_service, actor, receipt_check=lambda: None, receipt_consume=lambda: None
    ):
        with onboarding_service.registration_admission():
            if not onboarding_injected:
                from ..local_control import request as control_request, ControlError

                try:
                    state = control_request(
                        settings.bootstrap_socket,
                        dict(action="namespace-check", source_instance=request.source_instance),
                        timeout=50,
                    )["result"]
                except ControlError as exc:
                    raise HostRegistrationConflict(
                        "HOST_INTEGRATION_UPGRADE_REQUIRED"
                        if exc.code == "RETIREMENT_GUARD_CHANGED"
                        else "HOST_INTEGRATION_UNAVAILABLE"
                    ) from None
                if state.get("source_instance") != request.source_instance or type(state.get("closed")) is not bool:
                    raise HostRegistrationConflict("HOST_REGISTRATION_INVALID")
                if state["closed"]:
                    raise HostRegistrationConflict("HOST_SOURCE_CLOSED")
            from dataclasses import replace

            mapping = {}
            if settings.source_namespace:
                from ..registration_namespace import belongs

                if not belongs(request.source_instance, settings.source_namespace):
                    # Only a persisted actor-bound historical attempt may retain its
                    # old namespace. New caller-chosen namespaces are not admitted.
                    outcome = onboarding_service.registration_outcome(
                        request.source_instance, request.registration_id, actor
                    )
                    if outcome.get("identity_status") != "OUTCOME_UNCERTAIN":
                        raise HostRegistrationConflict("HOST_REGISTRATION_INVALID")
            fingerprint = request.intent_fingerprint()
            durable_request = request.durable_request()

            def bind_intent():
                return onboarding_service.registration_intent(
                    request.command(), request.registration_id, actor, fingerprint, durable_request
                )

            # Reserve before catalog POSTs or filesystem credentials. The actor/nonce
            # binding survives response loss and cannot be claimed by another request.
            receipt_check()
            onboarding_service.reserve_provider_identity(
                request.command(),
                request.registration_id,
                actor,
                intent={"fingerprint": fingerprint, "request": durable_request},
            )
            with onboarding_service.registration_guard(request.command(), request.registration_id, actor):
                bind_intent()
                if request.automatic_placement:
                    from .catalog import call

                    receipt_check()
                    onboarding_service.check_registration(request.command())
                    preview = onboarding_service.preview(request.onboarding_token)
                    if not preview or not request.registration_id:
                        raise CatalogError("SELECTION_REQUIRED")
                    resolved = call(
                        settings.bootstrap_socket,
                        dict(
                            action="resolve-placement",
                            provider=request.source_type,
                            hosts=preview["hosts"],
                            name=request.name,
                            host_types=request.host_types,
                            site_id=(request.references.get("site") or {}).get("id"),
                            default_site_slug=settings.default_site_slug,
                        ),
                    )
                    selected_site = resolved.get("references", {}).get("site", {})
                    if selected_site.get("slug"):
                        onboarding_service.check_placement(selected_site["slug"], request.name)
                    if resolved["issues"]:
                        raise CatalogError(
                            "CLUSTER_REVIEW_REQUIRED"
                            if any(i["kind"] == "cluster" for i in resolved["issues"])
                            else "SELECTION_REQUIRED"
                        )
                    if request.create_cluster and not resolved["create_cluster"]:
                        # A newly visible matching name is not proof of our previous
                        # CREATE. Preserve the original intent and require its receipt
                        # before accepting the resolved object as the target.
                        from uuid import UUID, uuid5
                        from .catalog import create_call

                        bind_intent()
                        operation_id = str(
                            uuid5(
                                UUID("b6c311eb-0d55-45af-80a5-b949a20bfe47"),
                                actor + ":" + request.source_instance + ":" + str(request.registration_id),
                            )
                        )
                        outcome = create_call(
                            settings.bootstrap_socket, dict(action="catalog-reconcile", operation_id=operation_id)
                        )
                        if (
                            outcome.get("status") != "CREATED"
                            or not isinstance(outcome.get("item"), dict)
                            or outcome["item"].get("id") != (resolved["references"].get("cluster") or {}).get("id")
                        ):
                            raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN)
                    request = request.model_copy(
                        update={
                            "references": resolved["references"],
                            "host_types": resolved["host_types"],
                            "create_cluster": resolved["create_cluster"],
                            "cluster_name": request.name,
                        }
                    )
                if request.create_cluster:
                    # Authorize the exact receipt before starting any optional remote write.
                    from uuid import UUID, uuid5
                    from .catalog import create_call

                    receipt_check()
                    onboarding_service.check_registration(request.command())
                    pending = catalog_validate(
                        settings.bootstrap_socket,
                        request.references,
                        request.host_types,
                        onboarding_service.preview(request.onboarding_token),
                        pending_cluster=True,
                    )
                    operation_id = str(
                        uuid5(
                            UUID("b6c311eb-0d55-45af-80a5-b949a20bfe47"),
                            actor + ":" + request.source_instance + ":" + str(request.registration_id),
                        )
                    )
                    bind_intent()
                    try:
                        outcome = create_call(
                            settings.bootstrap_socket,
                            dict(
                                action="registration-cluster",
                                operation_id=operation_id,
                                name=request.name,
                                source_instance=request.source_instance,
                                site_id=pending["references"]["site"]["id"],
                                cluster_type_id=pending["references"]["cluster_type"]["id"],
                            ),
                        )
                    except CatalogError as exc:
                        if exc.code == "UNAVAILABLE":
                            raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None
                        raise
                    if outcome.get("status") == "UNCERTAIN":
                        raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN)
                    if outcome.get("status") == "REFUSED":
                        raise CatalogError(outcome.get("error", "SELECTION_REQUIRED"))
                    if outcome.get("status") != "CREATED" or not outcome.get("item"):
                        raise CatalogError("CLUSTER_REVIEW_REQUIRED")
                    request = request.model_copy(
                        update={"references": {**pending["references"], "cluster": outcome["item"]}}
                    )
                try:
                    if request.references or request.host_types or onboarding_service.preview(request.onboarding_token):
                        mapping = catalog_validate(
                            settings.bootstrap_socket,
                            request.references,
                            request.host_types,
                            onboarding_service.preview(request.onboarding_token),
                            require_empty_cluster=True,
                        )
                        refs = mapping["references"]
                        types = mapping["host_types"]
                        if refs["cluster"]["name"] != request.name:
                            raise CatalogError("CLUSTER_REVIEW_REQUIRED")
                        request = request.model_copy(
                            update={
                                "site_slug": refs["site"]["slug"],
                                "cluster_name": refs["cluster"]["name"],
                                "platform_slug": refs["platform"]["slug"],
                                "device_role_slug": refs["device_role"]["slug"],
                                "cluster_type_slug": refs["cluster_type"]["slug"],
                                "device_type_slug": next(iter(types.values()))["slug"],
                            }
                        )
                    elif not onboarding_injected:
                        raise CatalogError("SELECTION_REQUIRED")
                    mapping["ip_conflict_policy"] = "observe"
                    registration = bind_intent()
                    receipt_consume()
                    onboarding_service.register(replace(request.command(), mapping=mapping), registration=registration)
                    return SourceDTO.from_view(
                        source_view(
                            {
                                **request.model_dump(),
                                "enabled": True,
                                "sync_enabled": False,
                                "legacy_identity_owner": False,
                            }
                        )
                    )
                except Exception:
                    if request.create_cluster:
                        # The durable catalog journal records the created cluster. Never
                        # delete it on registry/secret/receipt failure or claim no writes.
                        raise OnboardingError(ErrorCode.REGISTRATION_CLUSTER_RETAINED) from None
                    raise

    jobs = continuation = None
    if not onboarding_injected and settings.registration_dsn:
        from ..registration_jobs import RegistrationJobs, RegistrationContinuation

        jobs = RegistrationJobs(settings.registration_dsn, settings.registry_schema)

        def attest_registration(job):
            from ..local_control import request as control_request

            return (
                control_request(
                    settings.lifecycle_socket,
                    dict(
                        action="registration_credentials",
                        source_instance=job["source_instance"],
                        operation_id=str(job["operation_id"]),
                        actor_id=job["actor_id"],
                    ),
                )["result"].get("verified")
                is True
            )

        continuation = RegistrationContinuation(jobs, onboarding_service, complete_registration, attest_registration)
        from contextlib import asynccontextmanager
        import threading

        @asynccontextmanager
        async def registration_lifespan(app):
            stopped = threading.Event()

            def run():
                while not stopped.wait(5):
                    try:
                        continuation()
                    except Exception:
                        LOGGER.info("registration continuation unavailable")

            thread = threading.Thread(target=run, daemon=True, name="registration-continuation")
            thread.start()
            try:
                yield
            finally:
                stopped.set()
                # All underlying socket/DB operations have bounded timeouts;
                # shutdown never waits indefinitely for an unresponsive peer.
                thread.join(timeout=1)

        app.router.lifespan_context = registration_lifespan

    @router.post("/sources", response_model=SourceDTO, status_code=201)
    def register_source(request: RegistrationRequest, http: Request):
        actor = http.state.principal["principal_id"]
        check = lambda: auth_client.call(
            "receipt.check", session=http.cookies.get(COOKIE), receipt=request.onboarding_token
        )
        consume = lambda: auth_client.call(
            "receipt.consume",
            session=http.cookies.get(COOKIE),
            receipt=request.onboarding_token,
            destination=request.address,
            provider=request.source_type,
        )
        if jobs is None:
            return complete_registration(request, onboarding_service, actor, check, consume)
        from ..registration_jobs import StagedOnboarding

        with jobs.guard(request.source_instance):
            job = jobs.get(request.source_instance, request.registration_id, actor)
            if job is not None:
                original = RegistrationRequest.model_validate(
                    {**job["payload"]["request"], "onboarding_token": "x" * 32}
                )
                if original.intent_fingerprint() != request.intent_fingerprint():
                    raise HostRegistrationConflict("HOST_REGISTRATION_INTENT_CHANGED")
            if job is None or job["state"] == "STAGING":
                check()
                onboarding_service.check_registration(request.command())
                preview = onboarding_service.preview(request.onboarding_token)
                with onboarding_service.registration_admission():
                    # Validate the installation and closed-generation fence before
                    # credential creation, just as the completion path does.
                    from ..registration_namespace import belongs

                    if settings.source_namespace and not belongs(request.source_instance, settings.source_namespace):
                        outcome = onboarding_service.registration_outcome(
                            request.source_instance, request.registration_id, actor
                        )
                        if outcome.get("identity_status") != "OUTCOME_UNCERTAIN":
                            raise HostRegistrationConflict("HOST_REGISTRATION_INVALID")
                    from ..local_control import request as control_request, ControlError

                    try:
                        state = control_request(
                            settings.bootstrap_socket,
                            dict(action="namespace-check", source_instance=request.source_instance),
                            timeout=50,
                        )["result"]
                    except ControlError as exc:
                        raise HostRegistrationConflict(
                            "HOST_INTEGRATION_UPGRADE_REQUIRED"
                            if exc.code == "RETIREMENT_GUARD_CHANGED"
                            else "HOST_INTEGRATION_UNAVAILABLE"
                        ) from None
                    if state.get("source_instance") != request.source_instance or type(state.get("closed")) is not bool:
                        raise HostRegistrationConflict("HOST_REGISTRATION_INVALID")
                    if state["closed"]:
                        raise HostRegistrationConflict("HOST_SOURCE_CLOSED")
                    onboarding_service.reserve_provider_identity(
                        request.command(),
                        request.registration_id,
                        actor,
                        intent={"fingerprint": request.intent_fingerprint(), "request": request.durable_request()},
                    )
                    with onboarding_service.registration_guard(request.command(), request.registration_id, actor):
                        consume()
                        credentials = onboarding_service._pending.consume(request.onboarding_token)
                        job = jobs.begin(request, actor, preview, credentials.username)
                        jobs.stage(job, credentials, onboarding_service._secrets)
                        del credentials
            result = continuation.run(jobs.get(request.source_instance, request.registration_id, actor))
            if isinstance(result, SourceDTO):
                return result
            return SourceDTO.from_view(
                source_view(
                    {**request.model_dump(), "enabled": True, "sync_enabled": False, "legacy_identity_owner": False}
                )
            )

    @router.get("/registration-attempts")
    def pending_registrations(http: Request):
        actor = http.state.principal["principal_id"]
        saved = onboarding_service.pending_registrations(actor)
        durable = jobs.public_attempts(actor) if jobs else []
        current = {row["source_instance"] for row in durable}
        return {"attempts": durable + [row for row in saved if row["source_instance"] not in current]}

    @router.post("/sources/registration-status")
    def registration_status(request: RegistrationStatusRequest, http: Request):
        if jobs:
            job = jobs.get(request.source_instance, request.registration_id, http.state.principal["principal_id"])
            if job:
                if job["state"] == "COMPLETED":
                    return {
                        "status": "REGISTERED",
                        "source_instance": request.source_instance,
                        "source_url": "/sources/" + request.source_instance,
                    }
                return {
                    "status": "UNCERTAIN",
                    "server_continuing": job["state"] == "READY",
                    "resume_supported": job["state"] == "STAGING",
                    "safe_code": job["safe_code"],
                }
        # The browser never chooses a raw privileged catalog journal ID. Its
        # registration nonce is bound to the authenticated actor and source.
        identity = onboarding_service.registration_outcome(
            request.source_instance, request.registration_id, http.state.principal["principal_id"]
        )
        if identity["identity_status"] == "REGISTERED":
            return {**identity, "status": "REGISTERED"}
        pending_identity = identity["identity_status"] == "OUTCOME_UNCERTAIN"
        if identity["identity_status"] in {"RESTORE_REQUIRED", "IDENTITY_CONFLICT"}:
            return {**identity, "status": "UNCERTAIN"}
        from uuid import uuid5
        from .catalog import create_call

        operation_id = str(
            uuid5(
                UUID("b6c311eb-0d55-45af-80a5-b949a20bfe47"),
                http.state.principal["principal_id"]
                + ":"
                + request.source_instance
                + ":"
                + str(request.registration_id),
            )
        )
        try:
            result = create_call(settings.bootstrap_socket, dict(action="catalog-reconcile", operation_id=operation_id))
        except CatalogError:
            if pending_identity:
                return {**identity, "status": "UNCERTAIN", "resume_supported": True, "catalog_status": "UNCERTAIN"}
            raise
        if pending_identity:
            return {
                **identity,
                "status": "UNCERTAIN",
                "resume_supported": True,
                "catalog_status": (
                    result.get("status")
                    if result.get("status") in {"CREATED", "REFUSED", "UNCERTAIN", "EXISTS_REVIEW_REQUIRED"}
                    else "UNCERTAIN"
                ),
            }
        return {
            "status": (
                result.get("status")
                if result.get("status") in {"CREATED", "REFUSED", "UNCERTAIN", "EXISTS_REVIEW_REQUIRED"}
                else "UNCERTAIN"
            )
        }

    @router.post("/sources/cancel-onboarding", response_model=CancellationResult)
    def cancel_onboarding(request: CancellationRequest, http: Request):
        auth_client.call("receipt.cancel", session=http.cookies.get(COOKIE), receipt=request.onboarding_token)
        onboarding_service.cancel(request.onboarding_token)
        return CancellationResult()
