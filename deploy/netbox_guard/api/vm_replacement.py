from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .views import GuardView, _body
from ..dependencies import DependencyGuardBlocked
from .. import vm_replacement


class VMReplacementReview(GuardView):
    permission_classes = (IsAuthenticated,)
    namespace_required = False

    def get(self, request, pk):
        try:
            cluster = int(request.query_params.get('cluster_id', ''))
        except ValueError:
            raise DependencyGuardBlocked('REQUEST_INVALID') from None
        return Response(vm_replacement.review(request.user, pk,
            request.query_params.get('source_instance'), cluster))


class VMReplacementExecute(GuardView):
    def post(self, request, pk):
        value = _body(request, ('source_instance', 'cluster_id', 'nonce', 'expected', 'new_identity', 'name'))
        return Response(vm_replacement.execute(request.user, pk, value['source_instance'],
            value['cluster_id'], value['nonce'], value['expected'], value['new_identity'], value['name']))
