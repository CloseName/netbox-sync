"""Provider-neutral discovery records for hosts, guests, disks and interfaces."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiscoveredDisk:
    """Physical disk observations, with byte capacity and optional hardware identity/health."""

    path: str
    model: Optional[str]
    serial: Optional[str]
    size_bytes: int
    disk_type: Optional[str]
    health: Optional[str]


@dataclass
class DiscoveredStorage:
    """Provider storage-pool capacity and availability observed during discovery."""

    name: str
    storage_type: Optional[str]
    content: Optional[str]
    total_bytes: int
    used_bytes: int
    available_bytes: int
    active: bool


@dataclass
class DiscoveredCPU:
    """Host processor identity and physical/logical topology reported by the provider."""

    model: Optional[str]
    vendor: Optional[str]
    sockets: int
    cores: int
    logical_cpus: int


@dataclass
class DiscoveredHostInterface:
    """Host network observations including addresses, bridge ports and management use."""

    name: str
    interface_type: str | None = None
    active: bool = False
    autostart: bool = False
    method: str | None = None
    addresses: list[str] = field(default_factory=list)
    gateway: str | None = None
    bridge_ports: list[str] = field(default_factory=list)
    vlan_id: int | None = None
    vlan_aware: bool = False
    comments: str | None = None
    mac_address: str | None = None
    management: bool = False


@dataclass
class DiscoveredHost:
    """Source-bound host inventory with separate VM and LXC collections and provider evidence."""

    source: str
    source_instance: str
    legacy_identity_owner: bool
    source_id: str

    original_name: str
    normalized_name: str

    management_ip: Optional[str]

    hypervisor: str
    hypervisor_version: Optional[str]

    cpu: DiscoveredCPU
    memory_bytes: int

    manufacturer: Optional[str] = None
    model: Optional[str] = None

    disks: list[DiscoveredDisk] = field(default_factory=list)
    storages: list[DiscoveredStorage] = field(default_factory=list)
    interfaces: list[DiscoveredHostInterface] = field(default_factory=list)
    virtual_machines: list["DiscoveredVirtualMachine"] = field(default_factory=list)
    containers: list["DiscoveredContainer"] = field(default_factory=list)
    esxi_events: dict | None = None
    esxi_host_network: dict | None = None
    proxmox_host_network: dict | None = None
    connection_management: dict | None = None
    hardware_identity: dict | None = None


@dataclass
class DiscoveredVirtualDisk:
    """Guest disk capacity in bytes with optional storage and stable provider identifier."""

    name: str
    storage: Optional[str]
    size_bytes: int
    external_id: Optional[str] = None


@dataclass
class DiscoveredInterface:
    """Guest NIC observations with IP/VRF scope and recorded MAC/IP conflicts."""

    name: str
    mac_address: Optional[str]
    bridge: Optional[str]
    vlan_id: Optional[int]
    ip_addresses: list[str] = field(default_factory=list)
    external_id: Optional[str] = None
    network_observations: dict | None = None
    ip_vrf_id: int | None = None
    ip_scope_conflicts: list[dict] = field(default_factory=list)
    mac_scope_conflicts: list[dict] = field(default_factory=list)


@dataclass
class DiscoveredVirtualMachine:
    """VM identity, resources and networks; provider-specific ESXi identifiers remain optional."""

    source: str
    source_instance: str
    legacy_identity_owner: bool
    source_id: str
    node_source_id: str

    vmid: object
    original_name: str
    normalized_name: str

    status: str
    vcpus: int
    memory_bytes: int
    autostart: bool

    disks: list[DiscoveredVirtualDisk] = field(default_factory=list)
    interfaces: list[DiscoveredInterface] = field(default_factory=list)
    external_id: Optional[str] = None
    description: Optional[str] = None
    provider_object_id: Optional[str] = None
    esxi_instance_uuid: Optional[str] = None
    esxi_bios_uuid: Optional[str] = None


@dataclass
class DiscoveredContainer:
    """LXC identity, architecture, OS, swap and privilege state alongside guest resources."""

    source: str
    source_instance: str
    legacy_identity_owner: bool
    source_id: str
    node_source_id: str

    vmid: int
    original_name: str
    normalized_name: str

    status: str
    architecture: Optional[str]
    os_type: Optional[str]

    vcpus: int
    memory_bytes: int
    swap_bytes: int
    autostart: bool
    unprivileged: bool

    disks: list[DiscoveredVirtualDisk] = field(default_factory=list)
    interfaces: list[DiscoveredInterface] = field(default_factory=list)
