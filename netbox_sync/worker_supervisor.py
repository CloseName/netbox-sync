"""Fixed worker bundles with bounded process-group shutdown, no shell commands.

A failed member terminates its bundle; Docker restarts the complete service.
Children receive their own database role environment, never the sibling's DSN.
Independent sockets retain the existing peer authorization and mount boundaries.
"""
import argparse
import os
import signal
import subprocess
import sys
import time

BASE_ENV = frozenset({'PATH','LANG','LC_ALL','HOME','PYTHONPATH','PYTHONDONTWRITEBYTECODE',
    'SSL_CERT_FILE','REQUESTS_CA_BUNDLE','NETBOX_SYNC_REGISTRY_SCHEMA',
    'NETBOX_SYNC_GUARD_INSTANCE','NETBOX_SYNC_NETBOX_CONFIG_FILE',
    'NETBOX_SYNC_NETBOX_STATE_DIR','NETBOX_SYNC_APPLY_LOCK_PATH'})
ROLE_ENV = {
    'discovery_worker': {'NETBOX_SYNC_DISCOVERY_REGISTRY_DSN','NETBOX_SYNC_DISCOVERY_NB_API_URL','NETBOX_SYNC_OPERATION_WRITER_DSN'},
    'apply_worker': {'NETBOX_SYNC_APPLY_REGISTRY_DSN','NETBOX_SYNC_APPLY_NB_API_URL','NETBOX_SYNC_RUN_WRITER_DSN'},
    'bootstrap_worker': set(), 'retirement_worker': set(),
}


def members(bundle):
    if bundle == 'netbox':
        return [('bootstrap_worker', []), ('retirement_worker', [])]
    common = ['--secret-root','/run/secrets/netbox-sync',
              '--source-secret-root','/run/secrets/netbox-sync-sources',
              '--api-uid','10001','--child-uid','10001','--child-gid','10001']
    return [('discovery_worker', common + ['--socket','/run/netbox-sync-discovery/worker.sock',
        '--netbox-token-file','/run/secrets/netbox/read-token']),
        ('apply_worker', common + ['--socket','/run/netbox-sync-apply/worker.sock',
        '--netbox-token-file','/run/secrets/netbox/apply-token',
        '--lock-path','/run/netbox-sync-lock/apply.lock'])]


def child_environment(module, environment):
    allowed = BASE_ENV | ROLE_ENV[module]
    return {key: value for key, value in environment.items() if key in allowed}


def supervise(commands, *, grace=5):
    children = []
    stopping = False
    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command, environment in commands:
            children.append(subprocess.Popen(command, env=environment, start_new_session=True))
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(0.1)
        return 0 if stopping else 1
    finally:
        # Each group was created by this supervisor. Never enumerate or signal
        # unrelated PIDs. Groups also contain bounded cross-UID HTTP children.
        for child in children:
            try: os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(child.poll() is None for child in children):
            time.sleep(0.05)
        for child in children:
            # A leader may have exited while a grandchild still owns the lock.
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        for child in children:
            child.wait(timeout=2)


def health(bundle):
    # Exact peer-authenticated replies, not merely an existing socket path.
    endpoints = ([('/run/netbox-sync-bootstrap/worker.sock', 10001, 'action'),
                  ('/run/netbox-sync-retirement/worker.sock', 0, 'action')]
                 if bundle == 'netbox' else
                 [('/run/netbox-sync-discovery/worker.sock', 10001, 'operation'),
                  ('/run/netbox-sync-apply/worker.sock', 10001, 'operation')])
    program = """import json,socket,sys
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
 sock.settimeout(2);sock.connect(sys.argv[1])
 sock.sendall(json.dumps({sys.argv[2]:'health'}).encode()+b'\\n')
 sock.shutdown(socket.SHUT_WR)
 value=json.loads(sock.recv(4096))
 if value!={'ok':True,'result':{'status':'ok'}}:sys.exit(1)
"""
    for path, uid, key in endpoints:
        def identity():
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
        result = subprocess.run([sys.executable,'-c',program,path,key],
            env=child_environment('bootstrap_worker', os.environ),
            preexec_fn=identity, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            # The serial apply socket is occupied during its bounded operation.
            # A root-owned current-process marker expires after the existing
            # child/cleanup budget. Never treat a dead or indefinitely hung
            # member as healthy, and never use this as apply authorization.
            from .worker_activity import bounded_busy
            if bundle == 'sync' and path == '/run/netbox-sync-apply/worker.sock' and bounded_busy():
                continue
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', choices=('sync','netbox'))
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    if args.health:
        return health(args.bundle)
    return supervise([([sys.executable,'-B','-m','netbox_sync.' + module,*arguments],
        child_environment(module, os.environ)) for module, arguments in members(args.bundle)])


if __name__ == '__main__':
    sys.exit(main())
