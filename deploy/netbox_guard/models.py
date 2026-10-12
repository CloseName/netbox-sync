"""Independent records survive removal of the infrastructure objects."""
from django.db import models


class ProviderBinding(models.Model):
    """Accepted provider identity; independent of hypervisor sync_identities."""
    provider_key = models.CharField(max_length=512, unique=True)
    account = models.CharField(max_length=128)
    resource = models.CharField(max_length=16)
    object_id = models.PositiveBigIntegerField()
    object_created = models.DateTimeField()
    revision = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        permissions = [('manage_providerbinding', 'Review and accept provider bindings')]
        constraints = [models.UniqueConstraint(fields=('resource', 'object_id'), name='guard_provider_target')]


class ProviderFieldClaim(models.Model):
    binding = models.ForeignKey(ProviderBinding, on_delete=models.PROTECT)
    field = models.CharField(max_length=128)
    value = models.JSONField(null=True)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('binding', 'field'), name='guard_provider_field')]


class ProviderBindingChange(models.Model):
    nonce = models.UUIDField(primary_key=True)
    binding = models.ForeignKey(ProviderBinding, on_delete=models.PROTECT)
    actor = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    before = models.JSONField()
    after = models.JSONField()
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()

class ProviderInventory(models.Model):
    """Server registry including resources awaiting an explicit NetBox binding."""
    provider_key = models.CharField(max_length=512, primary_key=True)
    account = models.CharField(max_length=128, db_index=True)
    snapshot = models.JSONField()
    observed_at = models.DateTimeField()
    evidence_digest = models.CharField(max_length=64)

    class Meta:
        default_permissions = ()


class ProviderInventoryImport(models.Model):
    nonce = models.UUIDField(primary_key=True)
    account = models.CharField(max_length=128, db_index=True)
    actor = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


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
        permissions = [('retire_retirementintent', 'Execute guarded source retirement'), ('audit_retirementintent', 'Audit source ownership without retirement')]

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

class SourceClosure(models.Model):
    source_instance = models.CharField(max_length=128, primary_key=True)
    intent = models.OneToOneField(RetirementIntent, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        default_permissions = ()


class NetworkBinding(models.Model):
    """Operator-confirmed LAN identity; never inferred from a name or MAC globally."""
    vm = models.ForeignKey('virtualization.VirtualMachine', on_delete=models.CASCADE)
    interface_key = models.CharField(max_length=64)
    interface_id = models.PositiveBigIntegerField()
    prefix = models.ForeignKey('ipam.Prefix', on_delete=models.PROTECT)
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('vm','interface_key','prefix'), name='guard_network_binding')]
        default_permissions = ()


class AddressReservation(models.Model):
    nonce = models.UUIDField(primary_key=True)
    binding = models.ForeignKey(NetworkBinding, on_delete=models.CASCADE)
    address = models.OneToOneField('ipam.IPAddress', on_delete=models.SET_NULL, null=True)
    actor_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
