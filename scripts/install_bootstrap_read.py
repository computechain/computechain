#!/usr/bin/env python3
"""Explicit scoped installation of TLS bootstrap reads; never restart validators."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import ssl
import subprocess
from computechain.scripts import multisite as fleet
from computechain.scripts.install_multisite import safe_root
from computechain.scripts.bootstrap_read_service import configuration
from computechain.scripts import bootstrap_pki as pki


def identity(root,node,wan):
    root=safe_root(root); fleet.label(node)
    return {'request':str(pki.identity_init(root/'bootstrap-read'/node,node,wan)),'private_key_exported':False}


def install(root,node,spec,approved_sha):
    if os.geteuid()!=0: raise ValueError('root operator installation required')
    root=safe_root(root); fleet.label(node)
    if len(node)>24: raise ValueError('provider name too long')
    raw=Path(spec).read_bytes()
    if len(raw)>8192 or hashlib.sha256(raw).hexdigest()!=approved_sha: raise ValueError('approved TLS service spec SHA mismatch')
    value=json.loads(raw)
    if set(value)!={'format','chain_id','node','home_root','service','certificate_sha256'} or type(value['format']) is not int or value['format']!=1 or value['node']!=node or value['home_root']!=str(root):
        raise ValueError('invalid scoped TLS service spec')
    fleet.label(value['chain_id']); config=configuration(value['service'])
    home=root/'bootstrap-read'/node
    cert=home/'server.pem'; key=home/'tls-private.pem'
    if cert.is_symlink() or key.is_symlink() or key.stat().st_mode&0o077: raise ValueError('private TLS identity paths unsafe')
    certificate=ssl.PEM_cert_to_DER_cert(cert.read_text())
    if hashlib.sha256(certificate).hexdigest()!=value['certificate_sha256']: raise ValueError('TLS certificate differs from approval')
    # Verify certificate and node-local private key match before changing anything.
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(str(cert),str(key))
    manifest=fleet.checked_home(root/value['chain_id']/'nodes'/node)
    if config['upstream']!=f"http://127.0.0.1:{manifest['ports']['rpc']}": raise ValueError('wrong native loopback read source')
    host,port=config['listen'].rsplit(':',1)
    if host!=manifest['node']['host'] or int(port)!=manifest['ports']['p2p']+6: raise ValueError('wrong provider listener/port')
    expected={p['host'] for p in manifest['network_profile']['endpoints'].values() if p is not None}|{host}
    if set(config['allowed_sources'])!=expected: raise ValueError('TLS source ACL must equal approved WAN peers plus own host')
    username='cbr-'+node
    try:
        account=pwd.getpwnam(username)
        if account.pw_dir!=str(home) or account.pw_shell!='/usr/sbin/nologin': raise ValueError('existing account not this TLS service')
    except KeyError:
        subprocess.run(['useradd','--system','--no-create-home','--home-dir',str(home),'--shell','/usr/sbin/nologin',username],check=True)
        account=pwd.getpwnam(username)
    if (home/'service.json').exists(): raise ValueError('service already prepared; explicit rotation/review required')
    fleet.write(home/'service.json',config)
    for target in (home,*home.iterdir()):
        if target.is_symlink(): raise ValueError('TLS service tree must not contain symlinks')
        os.chown(target,account.pw_uid,account.pw_gid)
    home.chmod(0o700); key.chmod(0o600)
    ops=Path('/etc/computechain')/value['chain_id']/node
    if any(p.is_symlink() or p.stat().st_uid!=0 or p.stat().st_mode&0o022 for p in (ops,ops.parent,ops.parent.parent)):
        raise ValueError('operator configuration path unsafe')
    firewall=ops/'bootstrap-read.nft'
    table='cpc_bootstrap_'+node.replace('-','_')
    sources=', '.join(sorted(config['allowed_sources']))
    if firewall.exists(): raise ValueError('bootstrap ACL already installed')
    firewall.write_text(f'table inet {table} {{\n chain input {{\n type filter hook input priority 0; policy accept;\n ip daddr {host} tcp dport {port} ip saddr {{ {sources} }} accept\n ip daddr {host} tcp dport {port} drop\n }}\n}}\n')
    firewall.chmod(0o644)
    prefix='cpc-'+value['chain_id']+'-'+node
    runtime=root/'runtime'
    units={prefix+'-bootstrap-acl.service':f'''[Unit]
Description=CPC {node} scoped bootstrap TLS source ACL
After=network-online.target
[Service]
Type=oneshot
RemainAfterExit=true
ExecStart=/usr/sbin/nft --file {firewall}
[Install]
WantedBy=multi-user.target
''',prefix+'-bootstrap-read.service':f'''[Unit]
Description=CPC {node} restricted TLS bootstrap reads
After=network-online.target {prefix}-engine.service {prefix}-bootstrap-acl.service
Requires={prefix}-bootstrap-acl.service
[Service]
User={username}
WorkingDirectory={runtime}
Environment=PYTHONPATH={runtime}:{runtime}/.deps
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 -m computechain.scripts.bootstrap_read_service --config {home}/service.json --cert {cert} --key {key}
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=15
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=tmpfs
BindReadOnlyPaths={runtime} {home}
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LimitCORE=0
LimitNOFILE=256
Nice=10
Slice={prefix}.slice
MemoryMax=96M
TasksMax=16
[Install]
WantedBy=multi-user.target
'''}
    for name,content in units.items():
        target=Path('/etc/systemd/system')/name
        if target.exists() or target.is_symlink(): raise ValueError('existing bootstrap unit preserved')
        target.write_text(content); target.chmod(0o644)
    subprocess.run(['nft','--check','--file',str(firewall)],check=True,capture_output=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    return {'node':node,'tls_port':int(port),'units':list(units),'started':False,'validator_restarted':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['identity','install'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--node',required=True)
    parser.add_argument('--wan')
    parser.add_argument('--spec',type=Path)
    parser.add_argument('--spec-sha256')
    args=parser.parse_args()
    if args.command=='identity':
        if not args.wan: parser.error('--wan required')
        result=identity(args.root,args.node,args.wan)
    else:
        if args.spec is None or args.spec_sha256 is None: parser.error('approved --spec/--spec-sha256 required')
        result=install(args.root,args.node,args.spec,args.spec_sha256)
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
