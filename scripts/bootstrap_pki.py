"""Small devnet-only PKI: CA stays on controller; TLS private keys stay on providers."""
from __future__ import annotations
import ipaddress
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from computechain.scripts.multisite import outside_git


def command(args):
    subprocess.run(['openssl',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,umask=0o077)


def ca_init(home):
    home=outside_git(home)
    if home.exists(): raise ValueError('CA directory must be NEW')
    home.mkdir(parents=True,mode=0o700)
    command(['req','-x509','-newkey','ed25519','-nodes','-subj','/CN=CPC bootstrap devnet CA',
             '-keyout',str(home/'ca-private.pem'),'-out',str(home/'ca.pem'),'-days','365',
             '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign'])
    (home/'ca-private.pem').chmod(0o600)
    return home/'ca.pem'


def identity_init(home,name,address):
    home=outside_git(home)
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,39}',name): raise ValueError('unsafe provider name')
    ipaddress.IPv4Address(address)
    if home.exists(): raise ValueError('provider TLS home must be NEW; no key overwrite')
    home.mkdir(parents=True,mode=0o700)
    command(['req','-new','-newkey','ed25519','-nodes','-subj','/CN='+name,
             '-keyout',str(home/'tls-private.pem'),'-out',str(home/'request.pem'),
             '-addext','subjectAltName=IP:'+address])
    (home/'tls-private.pem').chmod(0o600)
    return home/'request.pem'


def issue(ca,request,address,output):
    ca=Path(ca); output=Path(output)
    address=str(ipaddress.IPv4Address(address))
    if output.exists() or output.is_symlink(): raise ValueError('certificate output must be NEW')
    key=ca/'ca-private.pem'
    if key.is_symlink() or key.stat().st_mode&0o077: raise ValueError('CA key must be private')
    # Never copy untrusted CSR extensions (e.g. CA:TRUE). Fixed server-only policy.
    with tempfile.TemporaryDirectory(prefix='cpc-cert-ext-') as directory:
        extensions=Path(directory)/'extensions.cnf'
        extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:'+address+'\n')
        command(['x509','-req','-in',str(request),'-CA',str(ca/'ca.pem'),'-CAkey',str(key),
                 '-set_serial',str(secrets.randbits(127)+1),'-days','30','-extfile',str(extensions),'-out',str(output)])
    return output
