"""An ordinary external deletion must not leave a claim for a reused object ID."""
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .dependencies import MODELS
from .models import CreationClaim

@receiver(post_delete, dispatch_uid='netbox_guard_invalidate_deleted_creation_claim')
def invalidate_claim(sender, instance, using, **kwargs):
    resource = next((kind for kind, label in MODELS.items()
                     if label.lower() == sender._meta.label_lower), None)
    if resource is not None:
        CreationClaim.objects.using(using).filter(resource=resource, object_id=instance.pk).delete()
