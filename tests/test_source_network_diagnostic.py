import errno
import socket
import ssl
from unittest.mock import patch, MagicMock
from deploy.source_network_diagnostic import inspect, route_for

def test_unexpected_dns_never_connects():
    with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('192.0.2.1',443))]),patch('socket.create_connection') as connect:
        assert inspect('esxi-dev-ba.indeed-id.hq','10.17.0.2',443,True)['dns']=='UNEXPECTED_ADDRESSES'
        connect.assert_not_called()

def test_route_and_safe_error_classification(tmp_path):
    path=tmp_path/'route';path.write_text('Iface Destination Gateway Flags RefCnt Use Metric Mask\neth0 00000000 0100000A 0003 0 0 0 00000000\n')
    assert route_for('10.17.0.2',path)=='eth0'
    for exc,code in [(TimeoutError('sensitive'),'TIMEOUT_OR_FILTERED_NOT_PROVEN'),(OSError(errno.ENETUNREACH,'sensitive'),'NETWORK_UNREACHABLE'),(ConnectionRefusedError(errno.ECONNREFUSED,'sensitive'),'CONNECTION_REFUSED')]:
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('10.17.0.2',443))]),patch('socket.create_connection',side_effect=exc):
            result=inspect('esxi-dev-ba.indeed-id.hq','10.17.0.2',443,True)
            assert result['network']==code and 'sensitive' not in str(result)


def test_tls_timeout_is_not_a_tcp_timeout():
    stream=MagicMock()
    context=MagicMock()
    context.wrap_socket.side_effect=TimeoutError('sensitive')
    with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('10.17.0.2',443))]),patch('socket.create_connection',return_value=stream),patch('ssl.create_default_context',return_value=context):
        result=inspect('esxi-dev-ba.indeed-id.hq','10.17.0.2',443,True)
        assert result['tcp']=='CONNECTED' and result['tls']=='TLS_TIMEOUT'
        assert 'network' not in result and 'sensitive' not in str(result)
