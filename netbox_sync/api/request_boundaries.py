"""Shared API request protection, safe errors and request logging."""

import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from ..application.observability import ErrorCode
from ..application.sources import SourceReadError
from ..application.runs import RunReadError
from ..application.schedules import ScheduleReadError
from ..application.onboarding import OnboardingError
from ..auth_policy import AuthError
from .dto import ErrorDTO, ErrorDetailDTO
from .discovery_client import DiscoveryRequestError
from .apply_client import ApplyRequestError
from .lifecycle_client import LifecycleRequestError
from .schedule_client import ScheduleRequestError
from .auth import COOKIE, PUBLIC, permission
from .catalog import CatalogError

LOGGER = logging.getLogger("netbox_sync.api")


def _error(request, status, code, message, diagnostic=None):
    request.state.error_code = code
    from ..worker_failure import ERRORS

    detail = ERRORS.get(code)
    diagnostic = diagnostic or {}
    dto = ErrorDTO(
        error=ErrorDetailDTO(
            code=code,
            message=message,
            request_id=request.state.request_id,
            event_id=diagnostic.get("event_id") or request.state.request_id,
            stage=diagnostic.get("stage") or (detail["stage"] if detail else None),
            reason=diagnostic.get("reason"),
            difference_categories=diagnostic.get("categories", []),
            recommended_action=detail["action"]["en"] if detail else None,
        )
    )
    content = dto.model_dump(mode="json")
    if not diagnostic:
        content["error"].pop("reason", None)
        content["error"].pop("difference_categories", None)
    return JSONResponse(
        status_code=status,
        content=content,
        headers={"Cache-Control": "no-store", "X-Request-ID": request.state.request_id},
    )


def _install_boundaries(app, settings, auth_client):
    from ..local_control import ControlError

    @app.exception_handler(AuthError)
    async def auth_error(request, exc):
        status = {
            "AUTH_REQUIRED": 401,
            "AUTH_REAUTH_REQUIRED": 403,
            "AUTH_DENIED": 403,
            "AUTH_INVALID": 401,
            "AUTH_RATE_LIMITED": 429,
            "ENROLLMENT_INVALID": 409,
            "POLICY_CONFLICT": 409,
            "POLICY_INVALID": 422,
            "TEAM_CONFLICT": 409,
            "TEAM_INVALID": 422,
            "POLICY_HOST_MANAGED": 403,
            "PROBE_RECEIPT_INVALID": 409,
            "LDAP_INVALID": 422,
            "LDAP_CONFLICT": 409,
            "LDAP_ACCESS_DENIED": 403,
            "LDAP_BIND_FAILED": 422,
            "LDAP_TLS_FAILED": 422,
        }.get(exc.code, 503)
        return _error(request, status, exc.code, "Authentication or policy request rejected")

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        known = {
            "BOOTSTRAP_CONFLICT",
            "BOOTSTRAP_NOT_READY",
            "BOOTSTRAP_INVALID",
            "BOOTSTRAP_BUSY",
            "SOURCE_APPLY_ACTIVE",
        }
        return _error(
            request,
            409 if exc.code in known else 503,
            exc.code if exc.code in known else "BOOTSTRAP_UNAVAILABLE",
            "Reload bootstrap state and review before retrying",
        )

    @app.exception_handler(LifecycleRequestError)
    async def lifecycle_error(request, exc):
        messages = {
            "RUN_RECONCILIATION_UNAVAILABLE": (
                409,
                "Run evidence is incomplete or exceeds the bounded review; no baseline decision was recorded",
            ),
            "SOURCE_ARCHIVED": (
                409,
                "This registration generation is permanently archived. Start a new registration; old operations cannot be reused.",
            ),
            "SOURCE_ARCHIVE_REVIEW_REQUIRED": (
                409,
                "Review and close the historical generation before a new registration.",
            ),
            "SOURCE_CREDENTIAL_CLEANUP_PENDING": (
                409,
                "NetBox outcome is confirmed; local credential cleanup is pending. Continue the original operation.",
            ),
            "SOURCE_RETIREMENT_REVIEW_REQUIRED": (
                409,
                "Review the owned NetBox objects before confirming source removal",
            ),
            "SOURCE_RETIREMENT_PENDING": (
                409,
                "Source retirement is awaiting its original receipt; do not start another write",
            ),
            "RETIREMENT_AUTH_FAILED": (
                403,
                "NetBox could not authenticate the integration token. Check expiry, revocation and token restrictions.",
            ),
            "RETIREMENT_TOKEN_WRITE_REQUIRED": (
                403,
                "The integration token forbids writes. Source audit requires write permission only to record its AUDIT_ONLY journal entry.",
            ),
            "RETIREMENT_AUDIT_PERMISSION_REQUIRED": (
                403,
                "The NetBox service account lacks audit permission on Guard RetirementIntent. Grant scoped audit permission; Sync Admin is a separate role.",
            ),
            "RETIREMENT_SOURCE_SCOPE_DENIED": (
                403,
                "Guard audit permission does not cover this Source ID. Review the ObjectPermission source_instance constraint.",
            ),
            "RETIREMENT_OBJECT_VIEW_DENIED": (
                403,
                "At least one source object is outside the service account view permissions. No object details were returned.",
            ),
            "RETIREMENT_UNAVAILABLE": (
                503,
                "The configured NetBox guard is unavailable or its installation identity is unverified",
            ),
            "RETIREMENT_CONFLICT": (409, "The retirement evidence changed; review the current operation"),
            "RETIREMENT_BLOCKED": (409, "Retirement was refused; shared, manual or unproven objects must be reviewed"),
            "RETIREMENT_PERMISSION_DENIED": (
                403,
                "NetBox refused the guard service account; review its narrowly scoped permissions",
            ),
            "RETIREMENT_OWNERSHIP_UNPROVEN": (
                409,
                "Creation ownership is not proved; no deletion is authorized by identity alone",
            ),
            "RETIREMENT_OWNERSHIP_CONFLICT": (409, "Object ownership conflicts with this source"),
            "RETIREMENT_DEPENDENCIES_CHANGED": (
                409,
                "Object generation, placement or dependencies changed; review again",
            ),
            "RETIREMENT_MANUAL_CHANGE": (409, "Manual field changes require review; no deletion was confirmed"),
            "RETIREMENT_PROTECTED_DEPENDENCY": (
                409,
                "A protected dependency must be resolved in NetBox before a new review",
            ),
            "RETIREMENT_GUARD_CHANGED": (409, "The pinned NetBox guard installation or protocol differs"),
            "RETIREMENT_SERVER_BUSY": (
                409,
                "The original NetBox operation is still being reconciled; wait for its receipt",
            ),
            "RETIREMENT_BUDGET_EXCEEDED": (
                409,
                "NetBox exceeded the removal budget and rolled back this attempt; inspect Guard diagnostics",
            ),
            "RETIREMENT_DATABASE_REFUSAL": (
                409,
                "NetBox refused and rolled back this transaction; inspect Guard diagnostics",
            ),
            "RETIREMENT_SOURCE_OBJECTS_REMAIN": (
                409,
                "Source-owned objects remain outside the expected placement; inspect their ownership and dependencies",
            ),
            "RETIREMENT_UNCERTAIN": (409, "Retirement outcome is not confirmed; check the original receipt"),
            "SOURCE_RECOVERY_NOT_REMOVED": (409, "This source is active; open its existing page"),
            "SOURCE_IDENTITY_UNSUPPORTED": (
                409,
                "This provider has no supported legacy hardware identity verification",
            ),
            "SOURCE_IDENTITY_CHANGED": (
                409,
                "Current hardware identity differs from the recorded source; do not reassign by address",
            ),
            "SOURCE_IDENTITY_UNPROVED": (
                409,
                "Fresh hardware evidence does not prove the historical NetBox source ownership",
            ),
            "SOURCE_IDENTITY_CONFLICT": (
                409,
                "Another retained source claims this hardware identity; administrator ownership review is required",
            ),
            "SOURCE_RECOVERY_IDENTITY_REVIEW": (
                409,
                "Hardware identity and original NetBox placement require administrator review",
            ),
            "SOURCE_RECOVERY_IDENTITY_CONFLICT": (409, "Another active source claims this host; recovery is blocked"),
            "SOURCE_RECOVERY_ACTIVE": (409, "A recovery attempt already exists; reconcile that attempt"),
            "SOURCE_RECOVERY_NOT_FOUND": (404, "Recovery attempt is unavailable for this user"),
            "SOURCE_RECOVERY_EVIDENCE_CHANGED": (409, "Recovery evidence changed; review it again"),
            "SOURCE_RECOVERY_CREDENTIALS_UNCONFIRMED": (
                409,
                "Credential ownership is unconfirmed; source remains removed",
            ),
            "SOURCE_RECOVERY_OUTCOME_UNCERTAIN": (
                409,
                "Credential creation may have started; automatic abandonment is forbidden",
            ),
            "SOURCE_DISCOVERY_REQUIRED": (409, "Run Discovery to refresh host mappings"),
            "SOURCE_NOT_FOUND": (404, "Source not found"),
            "SOURCE_ALREADY_REMOVED": (409, "Source is already removed"),
            "SOURCE_LIFECYCLE_CONFLICT": (409, "Source changed; review its current state"),
            "SOURCE_CONFIRMATION_INVALID": (422, "Enter the exact display name"),
            "SOURCE_OPERATION_ACTIVE": (409, "Wait for active Plan or Discovery to finish"),
            "SOURCE_APPLY_ACTIVE": (
                409,
                "The shared operation lock is busy; wait for synchronization or lifecycle work to finish",
            ),
            "SOURCE_APPLY_UNCONFIRMED": (409, "Synchronization outcome requires reconciliation"),
        }
        status, message = messages.get(exc.code, (503, "Source lifecycle is unavailable; reload to check its state"))
        return _error(request, status, exc.code if exc.code in messages else "LIFECYCLE_UNAVAILABLE", message)

    from ..host_registration import HostRegistrationConflict

    @app.exception_handler(HostRegistrationConflict)
    async def host_registration_error(request, exc):
        messages = {
            "HOST_SOURCE_CLOSED": "This source was fully removed. Start a new registration with a new Source ID.",
            "HOST_INTEGRATION_UPGRADE_REQUIRED": "NetBox Guard must support the source namespace check before registration. Ask the NetBox operator to update the integration.",
            "HOST_INTEGRATION_UNAVAILABLE": "The NetBox integration check is unavailable. No source registration was started.",
            "HOST_ARCHIVE_RECHECK_REQUIRED": "An archived generation was restored. An administrator must recheck its original Guard receipt before registration.",
            "HOST_SOURCE_ARCHIVE_REQUIRED": "This previous generation requires closure, not identity recovery. Review its retained objects and archive it before a new registration.",
            "HOST_LEGACY_PLACEMENT_PROTECTED": "This placement contains unverified legacy ownership. Select a separate placement or review the old object identity; isolation does not authorize adoption.",
            "HOST_REGISTRY_REVIEW_REQUIRED": "An existing ESXi source lacks verified hardware identity. Administrator identity review is required before adding a host.",
            "HOST_REGISTRATION_INTENT_CHANGED": "This attempt already started with different parameters. Restore the original confirmed parameters; do not create another source.",
            "HOST_REGISTRATION_INVALID": "A stable registration request ID is required. Reload the registration form.",
            "HOST_IDENTITY_UNAVAILABLE": "A reliable host identity could not be verified. Registration is blocked.",
            "HOST_SOURCE_REMOVED": "This host belongs to a removed source. An administrator must review recovery of the original source.",
            "HOST_ALREADY_REGISTERED": "This host already belongs to a source. Open that source; removed sources require administrator recovery.",
            "HOST_IDENTITY_CONFLICT": "Several source records contain the same host identifier. Administrator reconciliation is required.",
            "HOST_REGISTRATION_RESERVED": "An earlier registration reserved this host. Reconcile that attempt before registering again.",
        }
        request.state.error_code = exc.code
        existing = (
            exc.source_instance
            if exc.code
            in {
                "HOST_ALREADY_REGISTERED",
                "HOST_SOURCE_REMOVED",
                "HOST_REGISTRY_REVIEW_REQUIRED",
                "HOST_LEGACY_PLACEMENT_PROTECTED",
                "HOST_ARCHIVE_RECHECK_REQUIRED",
                "HOST_SOURCE_ARCHIVE_REQUIRED",
            }
            else None
        )
        details = {}
        if getattr(request.state, "principal", {}).get("role") == "admin" and exc.conflicts:
            from ..source_config import SOURCE_INSTANCE_PATTERN

            entries = [
                dict(source_instance=row["source_instance"], state=row["state"])
                for row in exc.conflicts[:100]
                if isinstance(row, dict)
                and isinstance(row.get("source_instance"), str)
                and SOURCE_INSTANCE_PATTERN.fullmatch(row["source_instance"])
                and row.get("state") in ("REGISTERED", "REMOVED")
            ]
            details = {"conflicts": entries, "conflicts_truncated": exc.conflicts_truncated}
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    **details,
                    "code": exc.code,
                    "message": messages[exc.code],
                    "request_id": str(request.state.request_id),
                    "existing_source": existing,
                    "source_url": "/sources/" + existing if existing else None,
                }
            },
        )

    @app.exception_handler(OnboardingError)
    async def onboarding_error(request, exc):
        errors = {
            "SOURCE_ALREADY_EXISTS": (409, "Source already exists"),
            "SOURCE_UNSUPPORTED": (422, "Source type is unsupported"),
            "SOURCE_DNS_FAILED": (422, "Source hostname could not be resolved"),
            "SOURCE_AUTH_FAILED": (422, "Source authentication failed"),
            "SOURCE_PERMISSION_DENIED": (
                422,
                "The source denied inventory access. Grant the service account read access at the ESXi host root, including children; keep lockdown enabled.",
            ),
            "HOST_IDENTITY_MISSING": (
                422,
                "ESXi returned no hardware UUID in either host summary or hardware data. Verify SMBIOS system UUID and inventory visibility with the ESXi administrator; names and IP addresses cannot replace it.",
            ),
            "HOST_IDENTITY_INVALID": (
                422,
                "ESXi returned an invalid or placeholder hardware UUID. Verify SMBIOS system identity on the host before retrying.",
            ),
            "HOST_IDENTITY_INCONSISTENT": (
                422,
                "ESXi summary and hardware return different BIOS UUIDs. Re-read both fields under the same service account and investigate the discrepancy before retrying; neither value was selected.",
            ),
            "HOST_INVENTORY_EMPTY": (
                422,
                "No ESXi host is visible to this account. Verify host-root read permissions and lockdown account access.",
            ),
            "SOURCE_TLS_FAILED": (422, "Source TLS verification failed"),
            "SOURCE_TIMEOUT": (504, "Source connection timed out"),
            "SOURCE_DESTINATION_DENIED": (422, "Source destination is not permitted"),
            "SOURCE_CONNECTION_FAILED": (502, "Source connection failed"),
            "ONBOARDING_TOKEN_INVALID": (409, "Onboarding expired or already consumed; test again"),
            "SECRET_STORE_FAILED": (503, "Protected secret storage is unavailable"),
            "REGISTRATION_UNAVAILABLE": (503, "Registration is unavailable"),
            "REGISTRATION_FAILED": (503, "Source registration failed"),
            "REGISTRATION_UNCERTAIN": (503, "Registration outcome requires operator reconciliation"),
            "REGISTRATION_CLUSTER_RETAINED": (503, "Cluster created; source registration requires reconciliation"),
        }
        status, message = errors[exc.code.value]
        if getattr(exc, "reserved_source_id", False):
            return _error(
                request,
                409,
                "SOURCE_ID_RESERVED",
                "This Source ID was previously used and is reserved by a removed source.",
            )
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(SourceReadError)
    async def source_error(request, exc):
        errors = {
            "SOURCE_DISCOVERY_REQUIRED": (409, "Run Discovery to refresh host mappings"),
            "SOURCE_NOT_FOUND": (404, "Source not found"),
            "SOURCE_DATA_INVALID": (503, "Source metadata is unavailable"),
            "REGISTRY_UNAVAILABLE": (503, "Source registry is unavailable"),
        }
        status, message = errors[exc.code.value]
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(DiscoveryRequestError)
    async def discovery_error(request, exc):
        errors = {
            "SOURCE_RETIREMENT_PENDING": (409, "Source removal is pending; new operations are blocked"),
            "SOURCE_ARCHIVED": (409, "This source generation is closed"),
            "SOURCE_DISCOVERY_REQUIRED": (409, "Run Discovery to refresh host mappings"),
            "SOURCE_NOT_FOUND": (404, "Source not found"),
            "SOURCE_DISABLED": (409, "Disabled sources cannot be discovered"),
            "CREDENTIAL_UNAVAILABLE": (503, "Discovery credentials are unavailable"),
            "REGISTRY_UNAVAILABLE": (503, "Discovery registry is unavailable"),
            "DISCOVERY_TIMEOUT": (504, "Discovery timed out"),
            "PROVIDER_UNAVAILABLE": (502, "Source discovery failed"),
            "NETBOX_UNAVAILABLE": (502, "NetBox comparison failed"),
            "DISCOVERY_FAILED": (502, "Discovery failed"),
            "DISCOVERY_RESPONSE_INVALID": (502, "Discovery returned an invalid response"),
            "DISCOVERY_UNAVAILABLE": (503, "Discovery worker is unavailable"),
            "OPERATIONS_UNAVAILABLE": (503, "Durable operations are unavailable"),
            "OPERATION_STILL_EXECUTING": (409, "The operation is still executing"),
            "PLAN_STALE": (409, "Plan is no longer current"),
        }
        from ..worker_failure import ERRORS

        status, message = errors.get(
            exc.code,
            (502, ERRORS[exc.code]["message"]["en"]) if exc.code in ERRORS else errors["DISCOVERY_UNAVAILABLE"],
        )
        return _error(request, status, exc.code, message)

    @app.exception_handler(ApplyRequestError)
    async def apply_error(request, exc):
        statuses = {
            "SOURCE_NOT_FOUND": 404,
            "SOURCE_DISABLED": 409,
            "PLAN_BLOCKED": 409,
            "PLAN_STALE": 409,
            "CONFIRMATION_INVALID": 409,
            "CONFIRMATION_EXPIRED": 409,
            "CONFIRMATION_SOURCE_MISMATCH": 409,
            "APPLY_LOCKED": 409,
            "OUTCOME_UNCERTAIN": 503,
        }
        diagnostic = dict(
            event_id=exc.event_id or request.state.request_id,
            reason=exc.reason,
            categories=exc.categories,
            stage="validation",
        )
        LOGGER.warning(
            json.dumps(
                dict(component="api", code=exc.code, request_id=request.state.request_id, **diagnostic), sort_keys=True
            )
        )
        return _error(request, statuses.get(exc.code, 503), exc.code, "Manual sync request failed", diagnostic)

    @app.exception_handler(RunReadError)
    async def run_read_error(request, exc):
        errors = {
            "RUN_NOT_FOUND": (404, "Synchronization run not found"),
            "RUN_FILTER_INVALID": (422, "Synchronization history filter is invalid"),
            "RUN_HISTORY_UNAVAILABLE": (503, "Synchronization history is unavailable"),
        }
        status, message = errors[exc.code.value]
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(ScheduleRequestError)
    async def schedule_error(request, exc):
        errors = {
            "SCHEDULE_INVALID": (422, "Scheduling settings are invalid"),
            "SCHEDULE_CONFLICT": (409, "Scheduling settings changed; refresh and try again"),
            "SOURCE_DISCOVERY_REQUIRED": (409, "Run Discovery to refresh host mappings"),
            "SOURCE_NOT_FOUND": (404, "Source not found"),
            "CONTROL_WORKER_UNAVAILABLE": (503, "Scheduling control is unavailable"),
            "CONTROL_REQUEST_FAILED": (503, "Scheduling update failed"),
        }
        status, message = errors.get(exc.code, errors["CONTROL_REQUEST_FAILED"])
        return _error(request, status, exc.code, message)

    @app.exception_handler(ScheduleReadError)
    async def schedule_read_error(request, exc):
        return _error(request, 503, exc.code, "Scheduling state is unavailable")

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        # Never trust/re-emit client correlation headers, URLs, query or body.
        request.state.request_id = str(uuid4())
        request.state.error_code = None
        request.state.run_id = None
        request.state.diagnostics_status = None
        try:
            if settings.public_url:
                from ..tls_config import public_authority

                authority = public_authority(settings.public_url)
                local_health = (
                    request.scope.get("client") is None
                    and request.method == "GET"
                    and request.scope["path"] == "/api/v1/health"
                    and request.headers.get("host") == "localhost"
                )
                if not local_health:
                    # Uvicorn proxy middleware is disabled. Only the private Unix
                    # listener (client=None) may carry the proxy's canonical scheme.
                    if (
                        request.scope.get("client") is not None
                        or request.headers.get("host") != authority
                        or request.headers.get("x-forwarded-proto") != "https"
                    ):
                        return _error(request, 403, "API_WRITE_FORBIDDEN", "Public HTTPS boundary required")
                    request.scope["scheme"] = "https"
            if request.url.path.startswith("/api/v1/") and (request.method, request.url.path) not in PUBLIC:
                from starlette.concurrency import run_in_threadpool

                try:
                    request.state.principal = await run_in_threadpool(
                        auth_client.call,
                        "authorize",
                        session=request.cookies.get(COOKIE),
                        audit=request.method not in ("GET", "HEAD", "OPTIONS"),
                        permission=(
                            "source.read"
                            if permission(request.method, request.url.path) == "unmapped.deny"
                            else permission(request.method, request.url.path)
                        ),
                    )
                    if permission(request.method, request.url.path) == "unmapped.deny":
                        known_path = request.url.path == "/api/v1/health" or any(
                            permission(method, request.url.path) != "unmapped.deny"
                            for method in ("GET", "POST", "PATCH")
                        )
                        return _error(
                            request,
                            405 if known_path else 404,
                            "API_METHOD_NOT_ALLOWED" if known_path else "API_NOT_FOUND",
                            "Endpoint not available",
                        )
                except AuthError as exc:
                    return await auth_error(request, exc)
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/v1/"):
                origin = urlsplit(request.headers.get("origin", ""))
                host = request.headers.get("host", "")
                if (
                    host
                    not in (
                        (public_authority(settings.public_url),)
                        if settings.public_url
                        else settings.allowed_write_hosts
                    )
                    or origin.netloc != host
                    or origin.scheme != request.url.scheme
                    or origin.path not in ("", "/")
                    or origin.query
                    or origin.fragment
                    or origin.username is not None
                    or request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none")
                    or request.headers.get("x-netbox-sync-csrf") != "same-origin"
                    or request.headers.get("content-type", "").split(";")[0] != "application/json"
                ):
                    response = _error(request, 403, "API_WRITE_FORBIDDEN", "Same-origin write protection failed")
                elif (
                    not request.headers.get("content-length", "").isdigit()
                    or int(request.headers["content-length"]) > 16384
                ):
                    response = _error(request, 413, "API_REQUEST_TOO_LARGE", "Request body is too large")
                else:
                    ready = True
                    bootstrap_failure = None
                    # These POSTs are actor-bound status reads, not write admission.
                    # They must remain available while an admitted catalog/removal
                    # operation briefly owns BootstrapStore's exclusive lock.
                    source_status = request.url.path == "/api/v1/sources/registration-status" or re.fullmatch(
                        r"/api/v1/sources/[^/]+/(removal-status|retirement-status)", request.url.path
                    )
                    if (
                        settings.bootstrap_socket
                        and request.url.path.startswith("/api/v1/sources")
                        and not source_status
                    ):
                        from starlette.concurrency import run_in_threadpool
                        from .bootstrap import BootstrapClient

                        try:
                            state = await run_in_threadpool(BootstrapClient(settings.bootstrap_socket).call, "status")
                            ready = state.status == "READY"
                        except ControlError as exc:
                            bootstrap_failure = (
                                "BOOTSTRAP_BUSY" if exc.code == "BOOTSTRAP_BUSY" else "BOOTSTRAP_UNAVAILABLE"
                            )
                        except Exception:
                            bootstrap_failure = "BOOTSTRAP_UNAVAILABLE"
                    if bootstrap_failure:
                        response = _error(
                            request,
                            503,
                            bootstrap_failure,
                            "NetBox setup state is temporarily unavailable; no new operation was admitted",
                        )
                    else:
                        response = (
                            await call_next(request)
                            if ready
                            else _error(request, 409, "BOOTSTRAP_NOT_READY", "Complete NetBox setup first")
                        )
            else:
                response = await call_next(request)
        except Exception:  # pylint: disable=broad-exception-caught
            response = _error(request, 500, "API_INTERNAL_ERROR", "API request failed")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        LOGGER.log(
            logging.ERROR if response.status_code >= 500 else logging.INFO,
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": "ERROR" if response.status_code >= 500 else "INFO",
                    "component": "api",
                    "request_id": request.state.request_id,
                    "run_id": request.state.run_id,
                    "actor_id": getattr(request.state, "principal", {}).get("principal_id"),
                    "source_instance": None,
                    "error_code": request.state.error_code,
                    "message": "HTTP request completed",
                    "status_code": response.status_code,
                    "diagnostics_status": request.state.diagnostics_status,
                }
            ),
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        codes = {404: ("API_NOT_FOUND", "Endpoint not found"), 405: ("API_METHOD_NOT_ALLOWED", "Method not allowed")}
        code, message = codes.get(exc.status_code, ("API_REQUEST_FAILED", "Request rejected"))
        return _error(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        if request.url.path == "/api/v1/sources/test-connection" and any(
            error.get("loc") == ("body", "address") for error in _exc.errors()
        ):
            return _error(request, 422, "SOURCE_ADDRESS_INVALID", "Use a bare hostname or IPv4 address")
        return _error(request, 422, "API_VALIDATION_FAILED", "Request validation failed")


def install_catalog_error_handler(app):
    """Register catalog translation at its original factory position."""

    @app.exception_handler(CatalogError)
    async def catalog_error(request, exc):
        known = {
            "BUSY",
            "CONFLICT",
            "CATALOG_CHANGED",
            "SELECTION_REQUIRED",
            "HOST_MAPPING_REQUIRED",
            "CLUSTER_SCOPE_MISMATCH",
            "CLUSTER_AMBIGUOUS",
            "CLUSTER_REVIEW_REQUIRED",
            "PERMISSION_DENIED",
            "AUTH_FAILED",
            "TLS_FAILED",
            "NETWORK_UNREACHABLE",
            "RESPONSE_INVALID",
            "UNAVAILABLE",
        }
        code = exc.code if exc.code in known else "UNAVAILABLE"
        status = (
            409
            if code
            in {
                "BUSY",
                "CONFLICT",
                "CATALOG_CHANGED",
                "SELECTION_REQUIRED",
                "HOST_MAPPING_REQUIRED",
                "CLUSTER_SCOPE_MISMATCH",
                "CLUSTER_AMBIGUOUS",
                "CLUSTER_REVIEW_REQUIRED",
            }
            else 503
        )
        return _error(
            request, status, "CATALOG_" + code.removeprefix("CATALOG_"), "NetBox selection could not be verified"
        )
