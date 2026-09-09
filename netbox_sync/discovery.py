from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiscoveredDisk:
    path: str
    model: Optional[str]
    serial: Optional[str]
    size_bytes: int
    disk_type: Optional[str]
    health: Optional[str]


@dataclass
class DiscoveredStorage:
    name: str
    storage_type: Optional[str]
    content: Optional[str]
    total_bytes: int
    used_bytes: int
    available_bytes: int
    active: bool


@dataclass
class DiscoveredCPU:
    model: Optional[str]
    vendor: Optional[str]
    sockets: int
    cores: int
    logical_cpus: int


@dataclass
class DiscoveredHostInterface:
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
    virtual_machines: list['DiscoveredVirtualMachine'] = field(default_factory=list)
    containers: list['DiscoveredContainer'] = field(default_factory=list)


@dataclass
class DiscoveredVirtualDisk:
    name: str
    storage: Optional[str]
    size_bytes: int


@dataclass
class DiscoveredInterface:
    name: str
    mac_address: Optional[str]
    bridge: Optional[str]
    vlan_id: Optional[int]
    ip_addresses: list[str] = field(default_factory=list)
    external_id: Optional[str] = None


@dataclass
class DiscoveredVirtualMachine:
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


@dataclass
class DiscoveredContainer:
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
