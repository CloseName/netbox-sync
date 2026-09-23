"""Independent records survive removal of the infrastructure objects."""
from django.db import models

class CreationClaim(models.Model):
    resource = models.CharField(max_length=16)
    object_id = models.PositiveBigIntegerField()
    source_instance = models.CharField(max_length=128)
    cluster_id = models.PositiveBigIntegerField()
    object_created = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('resource', 'object_id'), name='guard_created_object')]
        default_permissions = ()

class RetirementIntent(models.Model):
    nonce = models.UUIDField(primary_key=True)
    actor = models.CharField(max_length=128)
    source_instance = models.CharField(max_length=128)
    manifest = models.JSONField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        permissions = [('retire_retirementintent', 'Execute guarded source retirement')]

class RetirementReceipt(models.Model):
    intent = models.OneToOneField(RetirementIntent, on_delete=models.PROTECT, primary_key=True)
    digest = models.CharField(max_length=64)
    deleted = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()

class CreationReceipt(models.Model):
    nonce = models.UUIDField(primary_key=True)
    actor = models.CharField(max_length=128)
    source_instance = models.CharField(max_length=128)
    resource = models.CharField(max_length=16)
    object_id = models.PositiveBigIntegerField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        permissions = [('create_creationreceipt', 'Create source-owned objects with atomic claims')]

class GuardIdentity(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    identifier = models.UUIDField(unique=True)
    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='guard_single_identity')]
