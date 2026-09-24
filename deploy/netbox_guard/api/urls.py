from django.urls import path
from .views import Capabilities, CreateOwned, Review, Retire, Receipt, ReviewSource, RetireSource, CreationProof
urlpatterns = [
    path('sources/review/', ReviewSource.as_view()),
    path('sources/execute/', RetireSource.as_view()),
    path('capabilities/', Capabilities.as_view()),
    path('objects/create/', CreateOwned.as_view()),
    path('objects/receipts/<uuid:nonce>/', CreationProof.as_view()),
    path('retirements/review/', Review.as_view()),
    path('retirements/execute/', Retire.as_view()),
    path('retirements/<uuid:nonce>/', Receipt.as_view()),
]
