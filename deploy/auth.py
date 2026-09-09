#!/usr/bin/env python3
"""Root-only enrollment/recovery and explicit one-time managed-policy transition."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import install


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--invitation-file', type=Path)
    parser.add_argument('--ceiling', choices=('existing', 'public-ipv4'))
    parser.add_argument('action', choices=('invite', 'recover', 'revoke', 'managed'))
    args = parser.parse_args(argv)
    if getattr(os, 'geteuid', lambda: -1)() != 0:
        parser.error('Root is required')
    descriptor = None
    try:
        root = install.validate_root(args.root)
        if args.action in ('invite', 'recover'):
            if args.invitation_file is None or not args.invitation_file.is_absolute():
                raise ValueError('An absolute invitation file is required')
            parent = args.invitation_file.parent
            if parent.is_symlink() or parent.stat().st_uid != 0 or parent.stat().st_mode & 0o077:
                raise ValueError('Invitation directory must be root-owned and mode 0700')
            descriptor = os.open(args.invitation_file, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        if args.action == 'managed' and not args.ceiling:
            raise ValueError('Explicit ceiling required')
        command = install.compose_command(root, 'exec', '-T', '--user', '0',
            'netbox-sync-auth-worker', 'python', '-m', 'netbox_sync.auth_worker', args.action,
            *([args.ceiling] if args.ceiling else []))
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            raise ValueError('Auth control failed; verify worker and DB readiness')
        data = json.loads(result.stdout)
        if descriptor is not None:
            os.write(descriptor, (data['invitation']+chr(10)).encode())
            os.fsync(descriptor)
        print('Administrative operation completed; invitation expires in 15 minutes' if descriptor is not None
              else 'Administrative operation completed')
        return 0
    except Exception:
        print('Administrative operation failed; check protected configuration and worker readiness', file=sys.stderr)
        return 1
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == '__main__':
    raise SystemExit(main())
