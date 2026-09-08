#!/usr/bin/env python3
"""Mode-aware operator Compose entrypoint; never evaluates generated env as shell."""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import install


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/netbox-sync'))
    args, command = parser.parse_known_args(argv)
    if not command:
        parser.error('Compose arguments required')
    try:
        return install.run(install.compose_command(args.root, *command), check=False).returncode
    except (install.InstallError, OSError):
        print('Compose configuration unavailable or ingress mode invalid', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
