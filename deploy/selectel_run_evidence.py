"""Bounded, read-only evidence for an existing test Selectel run. No replay."""
from collections import Counter
from datetime import datetime, timezone
import json
import math
import re
import subprocess
import tempfile
from uuid import UUID

MAX_LOG_BYTES = 4 * 1024 * 1024
CONTAINERS = ('netbox', 'netbox-worker', 'netbox-sync-bootstrap-worker')
EXCEPTIONS = ('IntegrityError', 'DataError', 'OperationalError', 'ProgrammingError',
              'PermissionDenied', 'ValidationError', 'MemoryError', 'TimeoutError',
              'DependencyGuardBlocked', 'RequestDataTooBig')


def project_logs(text):
    """Return fixed categories only; no URLs, exception messages or identifiers."""
    statuses = Counter(re.findall(
        r'POST /api/plugins/netbox-sync-guard/providers/account-import/ HTTP/[0-9.]+["\s]+([1-5][0-9]{2})\b', text))
    return {
        'import_http_statuses': dict(sorted(statuses.items())),
        'exception_classes': [name for name in EXCEPTIONS if re.search(r'\b' + name + r':', text)],
        'worker_timeout_seen': 'WORKER TIMEOUT' in text,
        'traceback_seen': 'Traceback (most recent call last)' in text,
        'nonempty': bool(text.strip()),
    }


def read_logs(name, since, until):
    """Read only a bounded time window/tail; keep raw log output private."""
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                ['docker', 'logs', '--since', since, '--until', until, '--tail', '500', name],
                stdin=subprocess.DEVNULL, stdout=output, stderr=output, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            return {'available': False}
        if result.returncode:
            return {'available': False}
        size = output.tell()
        output.seek(0)
        text = output.read(MAX_LOG_BYTES).decode('utf-8', errors='replace')
        return {'available': True, 'possibly_truncated': size > MAX_LOG_BYTES or text.count('\n') >= 500,
                **project_logs(text)}


def report(root, account, nonce):
    """Never change account state; scope log observations to time, not attribution."""
    if not re.fullmatch(r'[0-9]{1,20}', account) or str(UUID(nonce)) != nonce:
        raise ValueError('Invalid run selection')
    state = json.loads((root / 'secrets/netbox/selectel' / (account + '.json')).read_text())
    if state.get('run_id') != nonce or state.get('error') != 'IMPORT_UNCONFIRMED':
        raise ValueError('Run changed or is not uncertain')
    start, finish = state.get('started_at'), state.get('finished_at')
    if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, finish))
            or not 0 < start <= finish or finish - start > 86400):
        raise ValueError('Invalid run time window')
    since = datetime.fromtimestamp(start - 60, timezone.utc).isoformat()
    until = datetime.fromtimestamp(finish + 120, timezone.utc).isoformat()
    return {'account': account, 'run_id': nonce, 'error': 'IMPORT_UNCONFIRMED',
            'duration_seconds': round(finish - start, 1),
            'import_intent_present': bool(re.fullmatch(r'[0-9a-f]{64}', str(state.get('import_digest', '')))),
            'since_utc': since, 'until_utc': until,
            'log_scope': 'time_window_only_not_proof_of_run_attribution',
            'logs': {name: read_logs(name, since, until) for name in CONTAINERS}}
