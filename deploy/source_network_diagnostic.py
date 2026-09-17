#!/usr/bin/env python3
"""Operator-only exact destination diagnostics; no credentials or provider requests."""
import argparse
import errno
import ipaddress
import json
import socket
import ssl
from pathlib import Path


def route_for(address, path='/proc/net/route'):
    target=int(ipaddress.IPv4Address(address));routes=[]
    try:
        for line in Path(path).read_text().splitlines()[1:]:
            parts=line.split()
            if len(parts)<8:continue
            network=int.from_bytes(bytes.fromhex(parts[1]),'little')
            mask=int.from_bytes(bytes.fromhex(parts[7]),'little')
            if int(parts[3],16)&1 and target&mask==network:
                routes.append((mask.bit_count(),parts[0]))
    except (OSError,ValueError):return 'ROUTE_METADATA_UNAVAILABLE'
    return max(routes)[1] if routes else 'NO_ROUTE'


def inspect(host, expected, port, connect=False):
    expected=str(ipaddress.IPv4Address(expected))
    result={'host':host,'expected_ip':expected,'port':port,'policy':'CHECK_IN_AUTHENTICATED_UI'}
    try:addresses=sorted({row[4][0] for row in socket.getaddrinfo(host,port,socket.AF_INET,socket.SOCK_STREAM)})
    except socket.gaierror:return dict(result,dns='DNS_FAILED')
    result['dns']='EXPECTED_ONLY' if addresses==[expected] else 'UNEXPECTED_ADDRESSES'
    result['route_interface']=route_for(expected)
    if addresses!=[expected] or not connect:return result
    try:
        with socket.create_connection((expected,port),timeout=5) as stream:
            result['tcp']='CONNECTED'
            with ssl.create_default_context().wrap_socket(stream,server_hostname=host):
                result['tls']='VERIFIED'
    except ssl.SSLCertVerificationError:result['tls']='CERTIFICATE_VERIFICATION_FAILED'
    except ssl.SSLError:result['tls']='TLS_HANDSHAKE_FAILED'
    except TimeoutError:
        if result.get('tcp')=='CONNECTED':result['tls']='TLS_TIMEOUT'
        else:result['network']='TIMEOUT_OR_FILTERED_NOT_PROVEN'
    except OSError as error:
        result['network']={errno.ECONNREFUSED:'CONNECTION_REFUSED',errno.ENETUNREACH:'NETWORK_UNREACHABLE',errno.EHOSTUNREACH:'HOST_UNREACHABLE'}.get(error.errno,'NETWORK_ERROR')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True)
    parser.add_argument('--expected-ip',required=True)
    parser.add_argument('--port',type=int,default=443)
    parser.add_argument('--connect',action='store_true',help='After explicit operator policy review, make one TCP/TLS connection only')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('Invalid port')
    print(json.dumps(inspect(args.host,args.expected_ip,args.port,args.connect),sort_keys=True))

if __name__=='__main__':main()
