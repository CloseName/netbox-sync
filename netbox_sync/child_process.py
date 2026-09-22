"""Bounded child cleanup; never replace the original timeout with kill errors."""
from contextlib import contextmanager
import os
import json
import time
import subprocess
import threading

REAP_TIMEOUT = 2


def _close_pipes(process):
    for name in ('stdin', 'stdout', 'stderr'):
        stream = getattr(process, name, None)
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _deferred_reap(process, lock_fd):
    try:
        process.wait()
    finally:
        _close_pipes(process)
        if lock_fd is not None:
            os.close(lock_fd)


def stop_child(process, lock_fd=None):
    """SIGKILL only this child, reap within budget, retain apply lock if alive.

    A misconfigured supervisor must return timeout evidence promptly. A daemon
    reaper owns any surviving child and a duplicate of the shared lock until exit.
    It never retries an application operation or starts a replacement process.
    """
    detail = {'termination': 'timeout', 'exception_class': 'TimeoutExpired'}
    try:
        process.kill()
    except ProcessLookupError:
        pass  # Child won the exit race; still collect its wait status.
    except OSError as exc:
        detail['cleanup_error'] = type(exc).__name__
    try:
        process.wait(timeout=REAP_TIMEOUT)
        detail['child_reaped'] = True
    except subprocess.TimeoutExpired:
        detail['child_reaped'] = False
        retained = os.dup(lock_fd) if lock_fd is not None else None
        process._deferred_reap = True
        threading.Thread(target=_deferred_reap, args=(process, retained), daemon=True).start()
    detail['phases'] = read_progress(process)
    detail['returncode'] = process.returncode
    return detail


PHASES = ('provider', 'netbox', 'planning', 'preflight', 'apply', 'esxi_connect', 'esxi_inventory',
          'esxi_properties', 'esxi_additional', 'esxi_conversion', 'esxi_disconnect',
          'netbox_mapping', 'netbox_review', 'netbox_simulation')


def phase_progress(stage, elapsed=None, *, failed=False, requests=None, objects=None):
    """Separate bounded metadata pipe: no source data, payload or stderr."""
    if stage not in PHASES:
        return
    try:
        fd = int(os.environ.get('NETBOX_SYNC_PROGRESS_FD', '-1'))
        value = {'phase': stage, 'state': 'started' if elapsed is None else ('failed' if failed else 'finished')}
        if elapsed is not None:
            value['duration_ms'] = min(86400000, max(0, int(elapsed * 1000)))
        for key, count in (('requests', requests), ('objects', objects)):
            if type(count) is int and 0 <= count <= 10000000: value[key] = count
        os.write(fd, (json.dumps(value)+'\n').encode())
    except (ValueError, OSError):
        pass


def read_progress(process):
    fd = getattr(process, '_progress_fd', None)
    rows = getattr(process, '_phases', [])
    if fd is not None:
        try:
            raw = os.read(fd, 8192)
        except (BlockingIOError, OSError):
            raw = b''
        for line in raw.splitlines():
            try:
                value = json.loads(line)
                if value.get('phase') in PHASES and value.get('state') in ('started','finished','failed'):
                    row = {'phase': value['phase'], 'state': value['state']}
                    if type(value.get('duration_ms')) is int and 0 <= value['duration_ms'] <= 86400000:
                        row['duration_ms'] = value['duration_ms']
                    for key in ('requests','objects'):
                        if type(value.get(key)) is int and 0 <= value[key] <= 10000000:
                            row[key] = value[key]
                    rows.append(row)
            except (ValueError, AttributeError):
                pass
    process._phases = rows[-32:]
    return process._phases


@contextmanager
def child_process(popen, *args, **kwargs):
    """Avoid Popen.__exit__'s unlimited wait; metadata survives a killed child."""
    read_fd = write_fd = None
    if os.name == 'posix':
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        kwargs['pass_fds'] = (*kwargs.get('pass_fds', ()), write_fd)
        kwargs['env'] = dict(kwargs.get('env', {}), NETBOX_SYNC_PROGRESS_FD=str(write_fd))
    process = None
    try:
        process = popen(*args, **kwargs)
        process._progress_fd = read_fd
        process._phases = []
        process._deferred_reap = False
        if write_fd is not None:
            os.close(write_fd)
            write_fd = None
        yield process
    finally:
        if process is not None:
            read_progress(process)
            process._progress_fd = None
            if not getattr(process, '_deferred_reap', False):
                _close_pipes(process)
        for fd in (read_fd, write_fd):
            if fd is not None:
                os.close(fd)


@contextmanager
def measured_phase(stage):
    """Timing-only nested stage; preserve the original exception and classification."""
    import time
    started = time.monotonic()
    phase_progress(stage)
    failed = True
    try:
        yield
        failed = False
    finally:
        phase_progress(stage, time.monotonic() - started, failed=failed)
