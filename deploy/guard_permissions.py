#!/usr/bin/env python3
"""Print non-secret, once-per-installation Guard permission constraints only."""
import argparse
import json
from pathlib import Path
import re


def specification(root):
    path=Path(root)/'state/installation-id'
    if path.is_symlink():raise ValueError('Installation identity must not be a link')
    namespace=path.read_text(encoding='ascii').strip()
    if not re.fullmatch('[a-f0-9]{32}',namespace):raise ValueError('Installation identity unavailable')
    constraint={'source_instance__startswith':'n'+namespace+'-'}
    return [dict(name='NetBox Sync creation '+namespace,object_type='netbox_guard.creationreceipt',
                 actions=['create'],constraints=constraint),
            dict(name='NetBox Sync lifecycle '+namespace,object_type='netbox_guard.retirementintent',
                 actions=['audit','retire'],constraints=constraint)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    try:print(json.dumps(specification(args.root),indent=2))
    except (OSError,ValueError):raise SystemExit('Prepared installation identity is unavailable; run installer --prepare-only first') from None


if __name__=='__main__':main()
