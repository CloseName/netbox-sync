from django.urls import path
from .views import Capabilities, CreateOwned, Review, Retire, Receipt, ReviewSource, RetireSource, CreationProof, SourceAudit, ArchiveReview, ArchiveExecute, SourceNamespaceState
from .pfsense import PfSenseImport, PfSensePreflight
urlpatterns = [
    path('pfsense/preflight/', PfSensePreflight.as_view()),
    path('pfsense/import/', PfSenseImport.as_view()),
    path('sources/<str:source>/state/', SourceNamespaceState.as_view()),
    path('sources/archive-review/', ArchiveReview.as_view()),
    path('sources/archive-execute/', ArchiveExecute.as_view()),
    path('sources/<str:source>/audit/', SourceAudit.as_view()),
    path('sources/review/', ReviewSource.as_view()),
    path('sources/execute/', RetireSource.as_view()),
    path('capabilities/', Capabilities.as_view()),
    path('objects/create/', CreateOwned.as_view()),
    path('objects/receipts/<uuid:nonce>/', CreationProof.as_view()),
    path('retirements/review/', Review.as_view()),
    path('retirements/execute/', Retire.as_view()),
    path('retirements/<uuid:nonce>/', Receipt.as_view()),
]
