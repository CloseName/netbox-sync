from django.urls import path
from . import network_views
urlpatterns = [
    path('networks/<str:kind>/<int:pk>/',network_views.networks,name='networks'),
    path('subnets/<int:pk>/',network_views.subnet,name='subnet'),
    path('subnets/<int:pk>/reserve/',network_views.reserve,name='reserve'),
]
