"""The platform allowlist must not conceal misspellings or application imports."""
import json
from pathlib import Path
import subprocess
import sys


def test_lint_platform_exceptions_are_narrow(tmp_path):
    probe = tmp_path / 'lint_probe.py'
    probe.write_text('import os\nimport fcntl\nos.geteuid()\nos.geteuid_typo()\n'
                     'import missing_application_module_for_lint\n', encoding='utf-8')
    config = Path(__file__).resolve().parents[1] / 'pyproject.toml'
    result = subprocess.run([
        sys.executable, '-m', 'pylint', '--rcfile', str(config),
        '--persistent=n', '--disable=all', '--enable=E,F', '--reports=n', '--score=n',
        '--output-format=json', str(probe),
    ], capture_output=True, text=True, check=False)
    messages = json.loads(result.stdout)
    assert result.returncode != 0
    assert sorted(row['symbol'] for row in messages) == ['import-error', 'no-member']
    assert 'geteuid_typo' in next(row['message'] for row in messages if row['symbol'] == 'no-member')
    assert 'missing_application_module_for_lint' in next(row['message'] for row in messages if row['symbol'] == 'import-error')
