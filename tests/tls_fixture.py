"""Ephemeral TEST-ONLY CA/server certificates; never used by the installer."""
import os
from pathlib import Path
import subprocess


def create_certificates(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    def openssl(*args):
        subprocess.run(['openssl',*args],cwd=root,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    openssl('req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','ca.pem',
            '-days','2','-subj','/CN=Disposable NetBox Sync Test CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
    openssl('req','-new','-newkey','rsa:2048','-nodes','-keyout','privkey.pem','-out','server.csr',
            '-subj','/CN=sync.example.test')
    (root/'extensions.cnf').write_text('subjectAltName=DNS:sync.example.test,DNS:netbox.example.test\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n')
    openssl('x509','-req','-in','server.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial',
            '-out','fullchain.pem','-days','2','-extfile','extensions.cnf')
    for name in ('privkey.pem','ca.key'): (root/name).chmod(0o600)
    (root/'ca.pem').chmod(0o644)
    return root


if __name__=='__main__':
    import shutil,tempfile
    # Only named disposable test volumes are mounted at these paths by the smoke.
    with tempfile.TemporaryDirectory() as directory:
        root=create_certificates(directory)
        for name in ('privkey.pem','fullchain.pem'):
            shutil.copyfile(root/name,Path('/tls')/name)
            os.chown(Path('/tls')/name,0,10001);(Path('/tls')/name).chmod(0o640)
        os.chown('/tls',0,10001);Path('/tls').chmod(0o750)
        shutil.copyfile(root/'ca.pem','/ca/netbox-ca.pem');Path('/ca/netbox-ca.pem').chmod(0o644)
        Path('/ca').chmod(0o755)
