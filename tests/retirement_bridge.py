"""Test-only TCP to Unix byte relay. No Docker API or application semantics."""
import select
import socket
import socketserver
from pathlib import Path
assert Path('/.dockerenv').is_file()
class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as upstream:
            upstream.settimeout(45);upstream.connect('/bridge/netbox.sock')
            self.request.settimeout(45)
            sockets=(self.request,upstream)
            while True:
                ready,_,_=select.select(sockets,[],[],45)
                if not ready:return
                for incoming in ready:
                    data=incoming.recv(65536)
                    if not data:return
                    (upstream if incoming is self.request else self.request).sendall(data)
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
with Server(('0.0.0.0',8443),Relay) as server:server.serve_forever()
