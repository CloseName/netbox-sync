"""Read-only paginated object/edge export for Map and future policy tooling."""
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .. import pfsense_catalog as catalog


class FirewallCatalog(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        page = catalog.page(request.user, request.GET)
        return Response(dict(schema='netbox-sync.firewall-catalog.v1', count=page.paginator.count,
            page=page.number, pages=page.paginator.num_pages,
            next_page=page.next_page_number() if page.has_next() else None,
            results=[{**catalog.document(request.user, hit['object']), 'matches': hit['reasons']} for hit in page]))


class FirewallObjectDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        return Response(catalog.document(request.user, catalog.object_for(request.user, uid)))
