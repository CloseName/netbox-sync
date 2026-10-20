"""Catalog route registration on the shared API router."""

from uuid import UUID
from fastapi import Query
from .catalog import CatalogError


def install_catalog_routes(router, *, settings, catalog_call, catalog_create_call):
    """Register existing catalog handlers with factory-supplied transports."""
    from .catalog_dto import CatalogCreateDTO

    @router.post("/catalog/{kind}")
    def create_catalog(kind: str, payload: CatalogCreateDTO):
        return catalog_create_call(
            settings.bootstrap_socket,
            dict(
                action="catalog-create",
                operation_id=str(payload.operation_id),
                kind=kind,
                object=payload.object,
                write_token=payload.write_token.get_secret_value(),
                confirm=payload.confirm,
            ),
        )

    @router.get("/catalog-operations/{operation_id}")
    def reconcile_catalog(operation_id: UUID):
        return catalog_create_call(
            settings.bootstrap_socket, dict(action="catalog-reconcile", operation_id=str(operation_id))
        )

    @router.get("/catalog/{kind}")
    def catalog(
        kind: str, search: str = Query(default="", max_length=100), offset: int = Query(default=0, ge=0, le=10000)
    ):
        from ..netbox_catalog import ENDPOINTS

        if kind not in ENDPOINTS:
            raise CatalogError("SELECTION_REQUIRED")
        return catalog_call(
            settings.bootstrap_socket, {"action": "list", "kind": kind, "search": search, "offset": offset}
        )
