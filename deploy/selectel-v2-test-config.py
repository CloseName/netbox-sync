"""Patch the defining config module; never depend on loader module registration."""
import ast
import os
from pathlib import Path
import stat
import sys
import tempfile

BEGIN = "# BEGIN managed Selectel v2 test mode"
END = "# END managed Selectel v2 test mode"
BLOCK = BEGIN + "\n" + "PLUGINS_CONFIG.setdefault('netbox_guard', {})['selectel_native_reconcile'] = True\n" + END + "\n"


def atomic_write(path, text):
    info = path.stat()
    fd, temporary = tempfile.mkstemp(prefix='.selectel-config-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(info.st_mode))
        if hasattr(os, 'chown'):
            os.chown(temporary, info.st_uid, info.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure(directory):
    directory = Path(directory)
    broken = directory / 'zzzz_selectel_v2_test.py'
    candidates = []
    config_references = False
    paths = sorted(directory.glob('*.py'), key=lambda p: (p.name != 'configuration.py', p.name))
    for path in paths:
        if path.is_symlink():
            raise RuntimeError('Symlink configuration is not supported')
        if path == broken or path.name.startswith('__'):
            continue
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text)
        config_references |= any(isinstance(n, ast.Name) and n.id == 'PLUGINS_CONFIG'
                                 for n in ast.walk(tree))
        # Patch only an explicit module-level definition, not a guessed module.
        for node in tree.body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(t, ast.Name) and t.id == 'PLUGINS_CONFIG' for t in targets):
                candidates.append((path, text))
                break
    if not candidates:
        # PLUGINS_CONFIG is optional. The test installation has only PLUGINS.
        # Do not overwrite conditional/imported settings that need inspection.
        path = directory / 'plugins.py'
        if config_references or not path.is_file():
            raise RuntimeError('Unresolved plugin configuration; no files changed')
        text = path.read_text(encoding='utf-8').rstrip() + '\n\nPLUGINS_CONFIG = {}\n'
    else:
        path, text = candidates[-1]
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise RuntimeError('Invalid managed config block; no files changed')
    if BEGIN in text:
        start = text.index(BEGIN)
        finish = text.index(END) + len(END)
        text = text[:start] + text[finish:]
    result = text.rstrip() + '\n\n' + BLOCK
    ast.parse(result)
    if broken.is_symlink():
        raise RuntimeError('Symlink override refused')
    atomic_write(path, result)
    if broken.exists():
        atomic_write(broken, '# Selectel setting is maintained in its defining configuration module.\n')
    return path.name


if __name__ == '__main__':
    directory = Path(sys.argv[1]).resolve()
    if not directory.is_relative_to(Path('/netbox-test')):
        raise SystemExit('Not a test configuration directory')
    print('Selectel test setting configured in: ' + configure(directory))
