"""Production HTTP boundary: API has a Unix listener only, never a TCP port."""
import http.client
import os
from pathlib import Path
import socket
import sys

SOCKET='/run/netbox-sync-http/api.sock'

class UnixHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def main():
    action=sys.argv[1]
    if action=='init':
        root=Path(SOCKET).parent
        if root.is_symlink():raise SystemExit('HTTP socket directory is invalid')
        info=root.stat()
        if (info.st_uid,info.st_gid,info.st_mode & 0o777)==(10001,10001,0o750):return
        if info.st_uid!=0:raise SystemExit('HTTP socket directory owner is invalid')
        os.chmod(root,0o750)
        os.chown(root,10001,10001)
    elif action in ('health','diagnostics'):
        connection=UnixHTTPConnection('localhost',timeout=2)
        try:
            headers={}
            if action=='diagnostics':
                from .tls_config import public_authority
                headers={'Host':public_authority(os.environ['NETBOX_SYNC_PUBLIC_URL']),'X-Forwarded-Proto':'https'}
            connection.request('GET','/api/v1/'+action,headers=headers)
            if connection.getresponse().status!=200:raise SystemExit(1)
        finally:connection.close()
    elif action=='serve':
        import uvicorn
        from .tls_config import public_authority
        public_authority(os.environ.get('NETBOX_SYNC_PUBLIC_URL',''))
        os.umask(0o077)
        uvicorn.run('netbox_sync.api.app:create_app',factory=True,uds=SOCKET,
                    proxy_headers=False,access_log=False,server_header=False)
    else:raise SystemExit('Unsupported HTTP runtime action')

if __name__=='__main__':main()
