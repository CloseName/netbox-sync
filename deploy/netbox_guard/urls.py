from django.urls import path
from . import network_views
from . import resource_registry_views
from . import provider_first_creation_views
urlpatterns = [
    path('providers/<str:account>/first-creation/<str:ref>/', provider_first_creation_views.first_creation, name='provider_first_creation'),
    path('providers/', resource_registry_views.registry, name='provider_resources'),
    path('providers/<str:account>/', resource_registry_views.registry, name='provider_resource_account'),
    path('networks/<str:kind>/<int:pk>/',network_views.networks,name='networks'),
    path('subnets/<int:pk>/',network_views.subnet,name='subnet'),
    path('subnets/<int:pk>/reserve/',network_views.reserve,name='reserve'),
]
