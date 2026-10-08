#!/usr/bin/env python3
"""Approved network-only update of an EXISTING home-contained fleet, without reset.

Separate public P2P endpoints from private host/RPC addresses. Apply only on a
stopped node, preserving genesis, registration, keys, signing state and all DBs.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from computechain.scripts import multisite as fleet
from computechain.scripts.install_multisite import safe_root

MAX_FILE=1024*1024
OPS_ROOT=Path('/etc/computechain')


def bounded(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor,'rb') as stream: raw=stream.read(MAX_FILE+1)
    if len(raw)>MAX_FILE: raise ValueError('network artifact too large')
    return raw


def digest(raw): return hashlib.sha256(raw).hexdigest()


def approved(path,expected):
    raw=bounded(path)
    if digest(raw)!=expected: raise ValueError('approved manifest SHA mismatch')
    return json.loads(raw),raw


def profile(value,manifest):
    if not isinstance(value,dict) or set(value)!={'format','chain_id','endpoints'} or type(value['format']) is not int or value['format']!=1 or value['chain_id']!=manifest['chain_id']:
        raise ValueError('invalid public P2P profile')
    nodes=[manifest['node'],*manifest['peers']]
    if not isinstance(value['endpoints'],dict) or set(value['endpoints'])!={n['name'] for n in nodes}:
        raise ValueError('one endpoint decision per registered node required')
    hosts={}; identities=set(); locations={}
    for node in nodes:
        endpoint=value['endpoints'][node['name']]
        if endpoint is None:
            if node['role']!='full': raise ValueError('validator requires a public P2P endpoint')
            continue
        if not isinstance(endpoint,dict) or set(endpoint)!={'host','port'}: raise ValueError('invalid public endpoint fields')
        address=ipaddress.IPv4Address(endpoint['host'])
        if not address.is_global or address.is_multicast or address.is_reserved or str(address)!=endpoint['host'] or type(endpoint['port']) is not int or not 1024<=endpoint['port']<=65535:
            raise ValueError('literal global IPv4 and bounded TCP port required')
        key=(endpoint['host'],endpoint['port'])
        if key in identities: raise ValueError('duplicate public P2P socket')
        identities.add(key)
        if node['host'] in hosts and hosts[node['host']]!=endpoint['host']: raise ValueError('one host must advertise one WAN address')
        hosts[node['host']]=endpoint['host']
        if endpoint['host'] in locations and locations[endpoint['host']]!=node['location']:
            raise ValueError('locations must not share a VPN/NAT exit address')
        locations[endpoint['host']]=node['location']
    return deepcopy(value)


def peer_addresses(manifest):
    network=profile(manifest['network_profile'],manifest)
    result=[]
    for peer in manifest['peers']:
        if peer['host']==manifest['node']['host']:
            result.append((peer,peer['host'],peer['ports']['p2p']))
        elif network['endpoints'][peer['name']] is not None:
            endpoint=network['endpoints'][peer['name']]
            result.append((peer,endpoint['host'],endpoint['port']))
    return result


def config_text(manifest,text):
    network=profile(manifest['network_profile'],manifest)
    peers=','.join(f"{p['node_id']}@{host}:{port}" for p,host,port in peer_addresses(manifest))
    endpoint=network['endpoints'][manifest['node']['name']]
    external='' if endpoint is None else f"{endpoint['host']}:{endpoint['port']}"
    changes={'external_address':json.dumps(external),'persistent_peers':json.dumps(peers),'pex':'false','seeds':'""'}
    match=re.search(r'(?ms)(^\[p2p\]\s*\n)(.*?)(?=^\[|\Z)',text)
    if match is None: raise ValueError('missing P2P configuration')
    body=match[2]
    for name,value in changes.items():
        body,count=re.subn(r'(?m)^'+name+r'\s*=.*$',lambda _:name+' = '+value,body)
        if count!=1: raise ValueError('missing/duplicate P2P field: '+name)
    return text[:match.start(2)]+body+text[match.end(2):]


def firewall_text(manifest):
    network=profile(manifest['network_profile'],manifest)
    # Private gateway keeps EXACT original source ACL. Public addresses are added
    # ONLY to the P2P set; no native RPC, ABCI, exporter or read gateway exposure.
    nodes=[manifest['node'],*manifest['peers']]
    original=manifest['_original_firewall']
    match=re.search(r'(set peers \{ type ipv4_addr; elements = \{ )(.*?)( \} \})',original)
    if match is None: raise ValueError('unexpected scoped firewall template')
    sources={n['host'] for n in nodes if n['host']==manifest['node']['host']}
    sources|={e['host'] for e in network['endpoints'].values() if e is not None}
    return original[:match.start(2)]+', '.join(sorted(sources))+original[match.end(2):]


def render(old,config,firewall,network,old_sha):
    new=deepcopy(old)
    new['network_profile']=profile(network,old)
    new['previous_manifest_sha256']=old_sha
    updated_config=config_text(new,config.decode()).encode()
    helper={**new,'_original_firewall':firewall.decode()}
    updated_firewall=firewall_text(helper).encode()
    new['files']['config.toml']=digest(updated_config)
    new['files']['firewall.nft']=digest(updated_firewall)
    return new,updated_config,updated_firewall


def plan(bundles,network,output):
    output=fleet.outside_git(output)
    if output.exists(): raise ValueError('network bundle output must be NEW')
    folders=sorted(p for p in Path(bundles).iterdir() if p.is_dir() and (p/'node.json').is_file())
    if not 6<=len(folders)<=16: raise ValueError('complete public fleet bundles required')
    prepared=[]
    for folder in folders:
        raw=bounded(folder/'node.json'); old=json.loads(raw)
        if old['node']['name']!=folder.name: raise ValueError('public bundle node name mismatch')
        data={}
        for name,sha in old['files'].items():
            if Path(name).name!=name: raise ValueError('invalid artifact name')
            data[name]=bounded(folder/name)
            if digest(data[name])!=sha: raise ValueError('original public bundle changed')
        new,config,firewall=render(old,data['config.toml'],data['firewall.nft'],network,digest(raw))
        data.update({'config.toml':config,'firewall.nft':firewall})
        prepared.append((new,data))
    if {n['node']['name'] for n,_ in prepared}!=set(network['endpoints']): raise ValueError('incomplete fleet')
    output.mkdir(parents=True,mode=0o700)
    result={'output':str(output),'manifest_sha256':{},'genesis_unchanged':True,'private_rpc_exposed':False}
    for new,data in prepared:
        folder=output/new['node']['name']; folder.mkdir(mode=0o700)
        for name,raw in data.items(): (folder/name).write_bytes(raw)
        fleet.write(folder/'node.json',new)
        result['manifest_sha256'][new['node']['name']]=fleet.digest_file(folder/'node.json')
    fleet.write(output/'network-profile.json',network)
    fleet.write(output/'approval.json',result)
    return result


def atomic_public(path,raw):
    path=Path(path)
    if path.is_symlink(): raise ValueError('refuse symlink target')
    old=path.stat()
    descriptor,temporary=tempfile.mkstemp(dir=path.parent,prefix='.network-')
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(raw); stream.flush()
            os.fchmod(stream.fileno(),old.st_mode&0o777)
            os.fchown(stream.fileno(),old.st_uid,old.st_gid)
            os.fsync(stream.fileno())
        os.replace(temporary,path)
        descriptor=os.open(path.parent,os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def stopped(manifest):
    prefix='cpc-'+manifest['chain_id']+'-'+manifest['node']['name']
    for suffix in ('engine','app','readrpc','rpc'):
        unit=prefix+'-'+suffix+'.service'
        if subprocess.check_output(['systemctl','show',unit,'-p','LoadState','--value'],text=True).strip()!='loaded':
            raise ValueError('expected installed unit not loaded')
        if subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','--value'],text=True).strip() not in ('inactive','failed'):
            raise ValueError('stop only this node services before network apply')


def nft_command(manifest,text,check=False):
    table='cpc_'+manifest['node']['name'].replace('-','_')
    # A single nft transaction replaces ONLY this node's existing table. No flush
    # or temporary allow-all window. Boot config remains just the table declaration.
    transaction='delete table inet '+table+'\n'+text
    args=['nft',*(['--check'] if check else []),'--file','-']
    subprocess.run(args,input=transaction,text=True,check=True,capture_output=True)


def apply(home,bundle,old_sha,new_sha):
    if os.geteuid()!=0: raise ValueError('explicit root operator required')
    home=Path(home).absolute(); bundle=Path(bundle).absolute()
    with fleet.operator_lock(home):
        old,old_raw=approved(home/'node.json',old_sha)
        new,new_raw=approved(bundle/'node.json',new_sha)
        root=safe_root(old['home_root'])
        if home!=root/old['chain_id']/'nodes'/old['node']['name']: raise ValueError('wrong home-contained node path')
        fleet.checked_home(home)
        stopped(old)
        config=bounded(home/'config/config.toml'); firewall=bounded(home/'firewall.nft')
        if digest(config)!=old['files']['config.toml'] or digest(firewall)!=old['files']['firewall.nft']:
            raise ValueError('old artifact changed after preflight')
        expected,new_config,new_firewall=render(old,config,firewall,new['network_profile'],old_sha)
        if new!=expected: raise ValueError('network update attempts to change immutable identity/artifacts')
        for name,sha in new['files'].items():
            if Path(name).name!=name or digest(bounded(bundle/name))!=sha: raise ValueError('new public bundle artifact mismatch')
        if bounded(bundle/'config.toml')!=new_config or bounded(bundle/'firewall.nft')!=new_firewall:
            raise ValueError('unexpected network configuration')
        ops=OPS_ROOT/old['chain_id']/old['node']['name']/'firewall.nft'
        for path in (ops,*list(ops.parents)[:3]):
            if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022: raise ValueError('root firewall path not trusted')
        if bounded(ops)!=firewall: raise ValueError('root firewall differs from approved old artifact')
        nft_command(old,new_firewall.decode(),check=True)
        # Back up only PUBLIC config/manifest, not keys, signer state or node DBs.
        backup=home/'network-backups'/old_sha
        if backup.exists() or backup.is_symlink(): raise ValueError('network backup already exists; inspect previous attempt')
        backup.mkdir(parents=True,mode=0o700)
        for name,raw in (('config.toml',config),('firewall.nft',firewall),('node.json',old_raw)):
            (backup/name).write_bytes(raw); (backup/name).chmod(0o600)
        preserved={p:fleet.digest_file(home/p) for p in ('owner-private.hex','config/node_key.json','config/priv_validator_key.json','data/priv_validator_state.json','config/genesis.json')}
        changed=[]
        try:
            for path,raw in ((home/'config/config.toml',new_config),(home/'firewall.nft',new_firewall),(ops,new_firewall)):
                changed.append(path); atomic_public(path,raw)
            nft_command(old,new_firewall.decode())
            atomic_public(home/'node.json',new_raw)
            fleet.checked_home(home)
            if any(fleet.digest_file(home/p)!=sha for p,sha in preserved.items()): raise RuntimeError('identity/history file changed')
        except Exception:
            for path in changed: atomic_public(path,config if path.name=='config.toml' else firewall)
            atomic_public(home/'node.json',old_raw)
            nft_command(old,firewall.decode())
            raise
        return {'node':old['node']['name'],'manifest_sha256':new_sha,'keys_and_signing_state_preserved':True,'genesis_unchanged':True,'services_started':False,'backup':str(backup)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','apply'])
    parser.add_argument('--bundles',type=Path)
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--home',type=Path)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--old-manifest-sha256')
    parser.add_argument('--manifest-sha256')
    args=parser.parse_args()
    fields=('bundles','profile','output') if args.command=='plan' else ('home','bundle','old_manifest_sha256','manifest_sha256')
    if any(getattr(args,f) is None for f in fields): parser.error('missing explicit inputs: '+', '.join(fields))
    result=plan(args.bundles,fleet.read(args.profile),args.output) if args.command=='plan' else apply(args.home,args.bundle,args.old_manifest_sha256,args.manifest_sha256)
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
