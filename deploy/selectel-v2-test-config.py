"""Late NetBox Docker configuration: preserve the effective plugin settings."""
from copy import deepcopy as _deepcopy
from pathlib import Path as _Path
import sys as _sys

# NetBox Docker executes each file in its own module, then resolves settings
# from the last loaded definition. There is no shared PLUGINS_CONFIG global.
_directory = _Path(__file__).parent
_previous = []
for _module in tuple(_sys.modules.values()):
    _file = getattr(_module, '__file__', None)
    if not _file:
        continue
    _path = _Path(_file)
    if _path.parent != _directory or _path.name == _Path(__file__).name:
        continue
    if _path.name != 'configuration.py' and _path.name >= _Path(__file__).name:
        continue
    if 'PLUGINS_CONFIG' in vars(_module):
        _previous.append((_path.name != 'configuration.py', _path.name,
                          vars(_module)['PLUGINS_CONFIG']))
if not _previous:
    raise RuntimeError('Selectel test: no previous PLUGINS_CONFIG definition')
PLUGINS_CONFIG = _deepcopy(sorted(_previous, key=lambda row: row[:2])[-1][2])
if not isinstance(PLUGINS_CONFIG, dict) or 'netbox_guard' not in PLUGINS_CONFIG:
    raise RuntimeError('Selectel test: existing netbox_guard configuration required')
PLUGINS_CONFIG['netbox_guard']['selectel_native_reconcile'] = True
