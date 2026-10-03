"""Guest interface presentation, deliberately independent of source identity."""
import hashlib


def interface_display_name(guest, nic):
    base = str(nic.bridge or nic.name)
    peers = [item for item in guest.interfaces
             if str(item.bridge or item.name).casefold() == base.casefold()]
    if len(peers) > 1 or len(base) > 64:
        key = str(getattr(nic, 'external_id', None) or nic.name)
        suffix = ' / ' + (key if len(key) <= 16 else hashlib.sha256(key.encode()).hexdigest()[:10])
        return base[:64 - len(suffix)] + suffix
    return base


def validate_interface_names(guest, existing, match, error_type):
    """Reject collisions before any writes, including rename cycles/manual rows."""
    names = set()
    for nic in guest.interfaces:
        name = interface_display_name(guest, nic)
        if name.casefold() in names:
            raise error_type(f'Duplicate desired interface name: {name!r}')
        names.add(name.casefold())
        owned = match(existing, guest, nic)
        for row in existing:
            if row.name.casefold() == name.casefold() and (
                owned is None or row.id != owned.id
            ):
                raise error_type(f'Interface name occupied: {name!r}; '
                                 'no interfaces were renamed or adopted')
