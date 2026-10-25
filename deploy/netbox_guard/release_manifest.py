"""Content identity of the deployed Guard, independent of image tags or mtimes."""
import hashlib
import json
from pathlib import Path


def manifest(root, overrides=None):
    files = {str(path.relative_to(root)).replace('\\', '/'): path
             for path in Path(root).rglob('*')
             if path.is_file() and path.suffix in ('.py', '.json', '.html')}
    files.update(overrides or {})
    return {name: hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for name, path in sorted(files.items())}


def fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
