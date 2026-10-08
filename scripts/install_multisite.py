#!/usr/bin/env python3
"""Explicit operator installation for home-contained fleet services (root required).

All source, dependencies, keys and databases stay below the operator's dedicated
home root. Only small root-owned systemd units and gateway/firewall configuration
are installed in /etc. This never modifies tunnels, SSH or existing firewall tables.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''): value.update(part)
    return value.hexdigest()


def safe_root(value):
    if not re.fullmatch(r'/(root|home/[a-z_][a-z0-9_-]*)/computechain-node',str(value)):
        raise ValueError('only dedicated computechain-node directories inside operator homes are allowed')
    path=Path(value)
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('operator home paths must not contain symlinks')
    return path


def checked_artifacts(root,chain,name,manifest_sha):
    home=root/chain/'nodes'/name
    descriptor=os.open(home/'node.json',os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor,'rb') as stream: raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=manifest_sha: raise ValueError('approved manifest SHA mismatch')
    manifest=json.loads(raw)
    if manifest.get('home_root')!=str(root) or manifest['chain_id']!=chain or manifest['node']['name']!=name:
        raise ValueError('installed node/profile identity mismatch')
    if manifest['application_home']!=str(root/chain/'apps'/name): raise ValueError('unexpected app home')
    for filename,digest in manifest['files'].items():
        if Path(filename).name!=filename: raise ValueError('invalid artifact name')
        target=home/'config'/filename if filename in ('config.toml','genesis.json') else home/filename
        if target.is_symlink() or sha(target)!=digest: raise ValueError('changed installed artifact')
    return home,manifest


def copy_owned(source,target,mode,approved_sha):
    # Engine users own their homes. Validate the SAME bounded bytes that are
    # installed: a second path-based copy after a hash check would be a TOCTOU
    # route from engine-writable Compose into a root Docker service.
    descriptor=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor,'rb') as stream: raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=approved_sha:
        raise ValueError('artifact changed before privileged installation')
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.stat().st_uid!=0 or sha(target)!=approved_sha:
            raise ValueError('refusing to overwrite a different existing system configuration: '+str(target))
        target.chmod(mode)
        return
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.chown(target,0,0); target.chmod(mode)


def install(root,chain,name,manifest_sha):
    root=safe_root(root)
    if os.geteuid()!=0: raise ValueError('explicit root installation required')
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,39}',chain) or not re.fullmatch(r'[a-z][a-z0-9-]{1,23}',name):
        raise ValueError('unsafe chain/node name')
    home,manifest=checked_artifacts(root,chain,name,manifest_sha)
    app=root/chain/'apps'/name
    # Separate locked accounts; no Docker group, no password, no unrelated HOME dirs.
    for username,folder in (('cpc-'+name,home),('cpa-'+name,app)):
        try:
            account=pwd.getpwnam(username)
            if account.pw_dir!=str(folder) or account.pw_shell!='/usr/sbin/nologin':
                raise ValueError('existing account is not this node service account')
        except KeyError:
            subprocess.run(['useradd','--system','--no-create-home','--home-dir',str(folder),'--shell','/usr/sbin/nologin',username],check=True)
            account=pwd.getpwnam(username)
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        folder.chmod(0o700)
        for target in (folder,*folder.rglob('*')):
            if target.is_symlink(): raise ValueError('node tree contains a symlink')
            os.chown(target,account.pw_uid,account.pw_gid)
    prefix='cpc-'+chain+'-'+name
    ops=Path('/etc/computechain')/chain/name
    ops.mkdir(parents=True,exist_ok=True,mode=0o755)
    for folder in (ops,*list(ops.parents)[:2]):
        if folder.is_symlink() or folder.stat().st_uid!=0 or folder.stat().st_mode&0o022:
            raise ValueError('root Docker configuration ancestors must not be user-writable')
    for filename in ('docker-compose.yml','rpc-nginx.conf','firewall.nft'):
        copy_owned(home/filename,ops/filename,0o644,manifest['files'][filename])
    if 'bootstrap_profile' in manifest:
        for filename in ('bootstrap-profile.json','bootstrap-ca.pem'):
            copy_owned(home/filename,ops/filename,0o644,manifest['files'][filename])
    systemd=Path('/etc/systemd/system')
    for filename in manifest['files']:
        if filename.endswith(('.service','.slice')):
            if not filename.startswith(prefix): raise ValueError('unexpected unit prefix')
            copy_owned(home/filename,systemd/filename,0o644,manifest['files'][filename])
    # A new, scoped firewall table survives node stop and is restored on reboot.
    firewall_unit=systemd/(prefix+'-firewall.service')
    content=f'''[Unit]
Description=ComputeChain {name} scoped private-port ACL
After=network-online.target
Before={prefix}-engine.service {prefix}-rpc.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft --file {ops}/firewall.nft
[Install]
WantedBy=multi-user.target
'''
    if firewall_unit.exists() and (firewall_unit.is_symlink() or firewall_unit.read_text()!=content):
        raise ValueError('existing firewall service differs')
    firewall_unit.write_text(content); firewall_unit.chmod(0o644)
    # Never leave the engine able to start before the dedicated port ACL.
    for suffix in ('engine','rpc'):
        drop=systemd/(prefix+'-'+suffix+'.service.d')
        drop.mkdir(exist_ok=True)
        target=drop/'10-private-acl.conf'
        content=f'[Unit]\nRequires={prefix}-firewall.service\nAfter={prefix}-firewall.service\n'
        if target.exists() and (target.is_symlink() or target.read_text()!=content): raise ValueError('existing ACL drop-in differs')
        target.write_text(content); target.chmod(0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    wrapper=root/'node.sh'
    content=f'''#!/bin/sh
set -eu
export PYTHONPATH={root}/runtime:{root}/runtime/.deps
export PYTHONDONTWRITEBYTECODE=1
export OPENSSL_CONF={root}/runtime/openssl.cnf
exec /usr/bin/python3 {root}/runtime/computechain/scripts/fleet_node.py --root {root} --chain {chain} "$@"
'''
    if wrapper.exists() and (wrapper.is_symlink() or wrapper.stat().st_uid!=0 or wrapper.read_text()!=content):
        raise ValueError('existing operator wrapper differs')
    wrapper.write_text(content); wrapper.chmod(0o755)
    # Installation does not activate services; doctor is run on-host before start.
    return {'installed':name,'home_root':str(root),'started':False,'accounts':['cpc-'+name,'cpa-'+name],
            'systemd_prefix':prefix,'ops':str(ops),'keys_exported':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--chain',required=True)
    parser.add_argument('--node',required=True)
    parser.add_argument('--manifest-sha256',required=True)
    args=parser.parse_args()
    print(json.dumps(install(args.root,args.chain,args.node,args.manifest_sha256),indent=2))


if __name__=='__main__': main()
