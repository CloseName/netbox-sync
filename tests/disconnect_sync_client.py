"""Test-only client: disconnect one accepted apply, without replaying it."""
import http.client
import json
import socket
import sys
import time

class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect('/run/netbox-sync-http/api.sock')

payload = json.load(sys.stdin)
headers = {'Content-Type': 'application/json', 'Host': 'sync.example.test',
           'Origin': 'https://sync.example.test', 'X-Forwarded-Proto': 'https',
           'X-NetBox-Sync-CSRF': 'same-origin', 'Cookie': payload['cookie']}
connection = UnixHTTP('sync.example.test')
connection.request('POST', payload['path'], json.dumps(payload['body']), headers)
for _ in range(150):
    check = UnixHTTP('sync.example.test')
    check.request('GET', '/api/v1/runs/' + payload['body']['run_id'], headers=headers)
    response = check.getresponse()
    state = json.loads(response.read())
    check.close()
    if response.status == 200 and state.get('status') == 'RUNNING' and state.get('plan_digest') == payload['digest']:
        break
    time.sleep(.1)
else:
    raise AssertionError('Test apply was not durably accepted')
connection.close()
print('Accepted apply HTTP client disconnected')
