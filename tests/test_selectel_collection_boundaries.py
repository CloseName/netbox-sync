"""Malformed pagination and API throttling retain bounded partial evidence."""
from unittest.mock import patch
from urllib.error import HTTPError
import pytest
from tools.selectel_audit.client import Client, AuditError, read_collection
from tools.selectel_audit.test_audit import FakeClient

URL = 'https://api.selectel.ru/resource'


@pytest.mark.parametrize('metadata', [
    {'links': [None]}, {'links': ['next']}, {'links': {'next': 17}},
    {'next': {'href': '?page=2'}}, {'links': {'next': False}},
    {'links': [{'rel': 'next'}]}, {'next': 'https://['},
])
def test_malformed_pagination_retains_page_with_explicit_failure(metadata):
    client = FakeClient([{'result': [{'id': 'one'}], **metadata}])
    items, pages, status = read_collection(client, URL, '', 'result')
    assert items == [{'id': 'one'}] and len(pages) == 1
    assert status == 'INVALID_PAGINATION_METADATA'
    assert len(client.calls) == 1


@pytest.mark.parametrize('limit', [0, False, True, -1, '200'])
def test_invalid_explicit_page_limit_is_not_empty_success(limit):
    client = FakeClient([{'result': [], 'limit': limit}])
    assert read_collection(client, URL, '', 'result', 'page')[2] == 'INVALID_PAGE_LIMIT'


def test_retry_after_is_honored_for_bounded_read_retry():
    client = Client()
    error = HTTPError(URL, 429, 'ignored', {'Retry-After': '7'}, None)
    with patch.object(client.opener, 'open', side_effect=[error, AuditError('STOP')]), \
         patch('tools.selectel_audit.client.time.sleep') as sleep:
        with pytest.raises(AuditError, match='STOP'):
            client.request(URL)
    sleep.assert_called_once_with(7)


def test_long_retry_after_does_not_retry_early_or_wait_unbounded():
    client = Client()
    error = HTTPError(URL, 429, 'ignored', {'Retry-After': '3600'}, None)
    with patch.object(client.opener, 'open', side_effect=error) as opened, \
         patch('tools.selectel_audit.client.time.sleep') as sleep:
        with pytest.raises(AuditError, match='HTTP_429'):
            client.request(URL)
    assert opened.call_count == 1
    sleep.assert_not_called()


def test_retry_after_http_date_and_invalid_value():
    from tools.selectel_audit.client import retry_delay
    with patch('tools.selectel_audit.client.time.time', return_value=0):
        assert retry_delay('Thu, 01 Jan 1970 00:00:09 GMT', 0) == 9
        assert retry_delay('not-a-date', 0) is None
        assert retry_delay(None, 1) == 2
