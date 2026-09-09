"""Guard the retain-only policy at the production call-site level."""

import ast
from pathlib import Path


def test_production_sync_contains_no_delete_calls():
    package = Path(__file__).parents[1] / 'netbox_sync'
    delete_calls = []
    setup_revocations = []

    for path in package.glob('*.py'):
        tree = ast.parse(
            path.read_text(encoding='utf-8'),
            filename=str(path),
        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'delete'
            ):
                if path.name == 'bootstrap_setup_probe.py':
                    # This fixed endpoint is independently checked for exact supplied-token identity.
                    assert ast.unparse(node.func.value) == 'session'
                    assert len(node.args) == 1 and ast.unparse(node.args[0]) == 'endpoint'
                    setup_revocations.append(node)
                    continue
                delete_calls.append(
                    f'{path.name}:{node.lineno}'
                )

    assert delete_calls == []
    assert len(setup_revocations) == 1
