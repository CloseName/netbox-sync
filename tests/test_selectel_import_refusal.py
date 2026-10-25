"""Known Guard refusals differ from a possibly committed import."""
import io
import json
from unittest.mock import patch
import pytest
from netbox_sync import selectel_collect
from netbox_sync.retirement_transport import GuardTransportError


@pytest.mark.parametrize('uncertain,expected', [
    (False, 'NETBOX_IMPORT_REFUSED'), (True, 'IMPORT_UNCONFIRMED')])
def test_guard_refusal_and_lost_response_are_distinct(capsys, uncertain, expected):
    error = GuardTransportError('PERMISSION_DENIED', uncertain=uncertain)
    with patch.object(selectel_collect.sys, 'stdin', io.StringIO('{"operation":"import"}')), \
         patch.object(selectel_collect, 'run', side_effect=error):
        selectel_collect.main()
    assert json.loads(capsys.readouterr().out) == {'error': expected}
