"""Provider-authoritative native fields. Unknown/retained data never clears fields."""
from .provider_policy import digest
from .hardware_identity import canonical

STATES = {'ACTIVE': 'active', 'SHUTOFF': 'offline', 'SHELVED': 'offline',
          'SHELVED_OFFLOADED': 'offline', 'ERROR': 'failed'}


def native_fields(snapshot):
    sections = snapshot.get('sections', {})
    def fresh(name):
        section = sections.get(name, {})
        return section.get('data', {}) if (section.get('status') == 'collected'
            and not section.get('retained') and isinstance(section.get('data'), dict)) else {}
    resource, hardware = fresh('resource'), fresh('hardware')
    result = {}
    name = resource.get('name') or resource.get('user_desc')
    if isinstance(name, str) and name.strip():
        name = name.strip()
        result['name'] = name if len(name) <= 64 else name[:49] + ' [' + digest(snapshot['identity'])[:10] + ']'
    if snapshot['identity']['kind'] == 'cloud_vm':
        if resource.get('status') in STATES and not resource.get('OS-EXT-STS:task_state'):
            result['status'] = STATES[resource['status']]
        for remote, local in (('vcpus', 'vcpus'), ('ram', 'memory')):
            value = hardware.get(remote)
            if type(value) is int and 0 < value <= 2147483647:
                result[local] = value
    else:
        serial = hardware.get('serial') or fresh('details').get('serial') or resource.get('serial')
        if canonical('system_serial', serial) and len(serial.strip()) <= 50:
            result['serial'] = serial.strip()
    return result
