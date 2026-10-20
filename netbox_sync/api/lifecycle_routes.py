"""Source lifecycle endpoint registration with factory-owned dependencies."""

from .lifecycle_client import LifecycleRequestError
from .operation_dto import LifecycleDTO, PlacementUpdateDTO, RemovalDTO, SourceNameDTO


def install_lifecycle_routes(router, *, settings, lifecycle_client, catalog_validate):
    """Keep lifecycle handlers on the shared router and application boundaries."""

    @router.get("/sources/{source_instance}/lifecycle", response_model=LifecycleDTO)
    def source_lifecycle(source_instance: str):
        return lifecycle_client.request(source_instance)

    @router.get("/sources/{source_instance}/placement")
    def source_placement(source_instance: str):
        return lifecycle_client.placement(source_instance)

    @router.patch("/sources/{source_instance}/placement", response_model=LifecycleDTO)
    def update_source_placement(source_instance: str, payload: PlacementUpdateDTO):
        current = lifecycle_client.placement(source_instance)
        if current["revision"] != payload.revision or current["discovery_id"] != str(payload.discovery_id):
            raise LifecycleRequestError("SOURCE_LIFECYCLE_CONFLICT")
        mapping = catalog_validate(
            settings.bootstrap_socket, payload.references, payload.host_types, current["preview"]
        )
        if payload.ip_conflict_policy is not None:
            mapping["ip_conflict_policy"] = payload.ip_conflict_policy
        if payload.network_scope_rules is not None:
            from .catalog import call  # pylint: disable=import-outside-toplevel

            mapping["network_scope_rules"] = call(
                settings.bootstrap_socket, {"action": "validate-scopes", "rules": payload.network_scope_rules}
            )["rules"]
        return lifecycle_client.request(
            source_instance,
            dict(
                revision=payload.revision,  # pylint: disable=use-dict-literal
                discovery_id=str(payload.discovery_id),
                mapping=mapping,
            ),
            action="save_placement",
        )

    @router.patch("/sources/{source_instance}/name", response_model=LifecycleDTO)
    def rename_source(source_instance: str, payload: SourceNameDTO):
        return lifecycle_client.request(source_instance, payload.model_dump(), action="rename_source")

    @router.post("/sources/{source_instance}/remove", response_model=LifecycleDTO)
    def remove_source(source_instance: str, payload: RemovalDTO):
        return lifecycle_client.request(source_instance, payload.model_dump())
