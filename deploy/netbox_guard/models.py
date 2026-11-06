"""Independent records survive removal of the infrastructure objects."""
from django.db import models
from django.urls import reverse
from uuid import uuid4
from netbox.models.features import CustomFieldsMixin


class ProviderAccountRun(models.Model):
    nonce = models.UUIDField(primary_key=True)
    account = models.CharField(max_length=20)
    actor = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


class ProviderResourceRegistry(models.Model):
    account = models.CharField(max_length=20, primary_key=True)
    revision = models.PositiveBigIntegerField(default=1)
    observed_at = models.DateTimeField()
    evidence_digest = models.CharField(max_length=64)
    snapshot = models.JSONField()

    class Meta:
        default_permissions = ()
        permissions = [('view_resourceregistry', 'View all provider resource registries'),
                       ('manage_resourceregistry', 'Import provider resource registries'),
                       ('manage_providerresourceregistry', 'Import provider resource registries (NetBox object permission)')]


class ProviderResourceRegistryChange(models.Model):
    nonce = models.UUIDField(primary_key=True)
    registry = models.ForeignKey(ProviderResourceRegistry, on_delete=models.PROTECT)
    actor = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    revision = models.PositiveBigIntegerField()
    before = models.JSONField(null=True)
    after = models.JSONField()
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


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


class ProviderCreatedObject(models.Model):
    """Creation provenance, never inferred from a name, binding or current fields."""
    account = models.CharField(max_length=20, db_index=True)
    model_label = models.CharField(max_length=100)
    object_id = models.PositiveBigIntegerField()
    object_created = models.DateTimeField()
    provider_key = models.CharField(max_length=512, blank=True)
    resource_key = models.CharField(max_length=512, blank=True)
    projection_values = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('model_label', 'object_id'), name='guard_provider_created_object')]


class ProviderDetachedResource(models.Model):
    provider_key = models.CharField(max_length=512, primary_key=True)
    account = models.CharField(max_length=20, db_index=True)
    class Meta:
        default_permissions = ()


class ProviderAccountFence(models.Model):
    account = models.CharField(max_length=20, primary_key=True)
    deleted = models.BooleanField(default=False)
    class Meta:
        default_permissions = ()


class ProviderLifecycleReceipt(models.Model):
    nonce = models.UUIDField(primary_key=True)
    account = models.CharField(max_length=20)
    actor = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        default_permissions = ()


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


class ProviderIPAMObject(models.Model):
    """Accepted provider identity and immutable native identity fields, not a CF."""
    key = models.CharField(max_length=512, unique=True)
    kind = models.CharField(max_length=16)
    object_id = models.PositiveBigIntegerField()
    object_created = models.DateTimeField()
    claims = models.JSONField()

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('kind', 'object_id'), name='guard_provider_ipam_target')]


class ProviderNetworkLink(models.Model):
    """Allocation/segment/port attachment; never an inferred interface or cable."""
    binding = models.ForeignKey(ProviderBinding, on_delete=models.PROTECT)
    native = models.ForeignKey(ProviderIPAMObject, on_delete=models.PROTECT)
    relation = models.CharField(max_length=16)
    evidence = models.JSONField()

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('binding', 'native', 'relation'), name='guard_provider_network_link')]


class ProviderIPAMReceipt(models.Model):
    nonce = models.UUIDField(primary_key=True)
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


class FirewallAppliance(models.Model):
    """Inventory scope, authorized through the existing NetBox VM."""
    vm = models.OneToOneField('virtualization.VirtualMachine', on_delete=models.CASCADE)
    observed_at = models.DateTimeField()
    version = models.CharField(max_length=256)
    coverage = models.JSONField(default=dict)
    digest = models.CharField(max_length=64)

    class Meta:
        default_permissions = ()

    def get_absolute_url(self):
        return reverse('plugins:netbox_guard:pfsense_appliance', kwargs={'pk': self.pk})

    def __str__(self):
        return str(self.vm)


class FirewallObject(CustomFieldsMixin, models.Model):
    """One scoped configuration object; references never allocate native IPs."""
    uid = models.UUIDField(default=uuid4, unique=True, editable=False)
    appliance = models.ForeignKey(FirewallAppliance, on_delete=models.CASCADE, related_name='entries')
    identity_key = models.CharField(max_length=80)
    identity_kind = models.CharField(max_length=16)
    component = models.CharField(max_length=32)
    table = models.CharField(max_length=32)
    category = models.CharField(max_length=16, db_index=True)
    name = models.CharField(max_length=256)
    position = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)
    state = models.CharField(max_length=16, default='current', db_index=True)
    data = models.JSONField(default=dict)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    class Meta:
        default_permissions = ()
        ordering = ('appliance_id', 'component', 'table', 'position', 'pk')
        constraints = [models.UniqueConstraint(fields=('appliance', 'identity_key'), name='guard_firewall_identity')]

    def get_absolute_url(self):
        return reverse('plugins:netbox_guard:pfsense_object', kwargs={'uid': self.uid})

    def __str__(self):
        return self.name


class FirewallReference(models.Model):
    source = models.ForeignKey(FirewallObject, on_delete=models.CASCADE, related_name='references')
    target = models.ForeignKey(FirewallObject, on_delete=models.CASCADE, related_name='referenced_by')
    field = models.CharField(max_length=64)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('source', 'target', 'field'), name='guard_firewall_reference')]
