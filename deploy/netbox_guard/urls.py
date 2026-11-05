from django.urls import path
from . import network_views
from . import resource_registry_views
from . import provider_first_creation_views
from . import provider_manual_link_views
from . import provider_unlink_views
from . import routing_views
urlpatterns = [
    path('routing/', routing_views.overview, name='routing_overview'),
    path('providers/<str:account>/unlink/<str:ref>/', provider_unlink_views.unlink, name='provider_unlink'),
    path('providers/<str:account>/link/<str:ref>/', provider_manual_link_views.manual_link, name='provider_manual_link'),
    path('providers/<str:account>/first-creation/<str:ref>/', provider_first_creation_views.first_creation, name='provider_first_creation'),
    path('providers/', resource_registry_views.registry, name='provider_resources'),
    path('providers/<str:account>/', resource_registry_views.registry, name='provider_resource_account'),
    path('networks/<str:kind>/<int:pk>/',network_views.networks,name='networks'),
    path('subnets/<int:pk>/',network_views.subnet,name='subnet'),
    path('subnets/<int:pk>/reserve/',network_views.reserve,name='reserve'),
]
