#!/usr/bin/env python3
"""Admit a NEW outbound-only full follower to an existing approved devnet genesis."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from computechain.scripts import multisite as fleet
from computechain.scripts import fleet_network as network
from computechain.scripts import bootstrap_protocol as bootstrap


def create(root,inventory_file,reference,name,profile_file,profile_sha,ca,output,binary):
    root=Path(fleet.home_root(str(root)))
    original=fleet.inventory(fleet.read(inventory_file))
    ref=fleet.read(Path(reference)/'node.json')
    if ref['chain_id']!=original['chain_id'] or ref['inventory_sha256']!=hashlib.sha256(fleet.canonical(original)).hexdigest():
        raise ValueError('reference genesis inventory mismatch')
    for filename,sha in ref['files'].items():
        if Path(filename).name!=filename or network.digest(network.bounded(Path(reference)/filename))!=sha:
            raise ValueError('approved reference artifact changed')
    if ref['node']['host'] not in {n['host'] for n in original['nodes']} or ref.get('home_root')!=str(root):
        raise ValueError('new follower must use this approved operator host/home root')
    if name in {n['name'] for n in original['nodes']}: raise ValueError('choose a NEW full node name')
    fleet.label(name)
    public,public_raw=network.approved(profile_file,profile_sha)
    bootstrap.profile(public,{'schema':3,'chain_id':ref['chain_id'],'genesis_sha256':ref['genesis_sha256']})
    bootstrap.trust_context(ca,public['ca_sha256'])
    peers=[{**ref['node'],'ports':ref['ports'],'node_id':ref['registration']['node_id']},*ref['peers']]
    for provider in public['providers']:
        peer=next((p for p in peers if p['name']==provider['name'] and p['witness']),None)
        if peer is None or peer['node_id']!=provider['node_id'] or peer['location']!=provider['location']:
            raise ValueError('bootstrap providers not approved existing witnesses')
        if provider['url'].split('://',1)[1].split(':',1)[0]!=ref['network_profile']['endpoints'][provider['name']]['host']:
            raise ValueError('TLS provider WAN differs from approved P2P location')
    spec={**ref['node'],'name':name,'role':'full','stake_cpc':0,'witness':False}
    joined=deepcopy(original); joined['nodes'].append(spec); fleet.inventory(joined)
    home=root/ref['chain_id']/'nodes'/name
    output=fleet.outside_git(output)
    if home.exists() or home.is_symlink() or output.exists(): raise ValueError('follower home/bundle output must be NEW; no reset')
    # Only the NEW follower signs this separate admission inventory. The original
    # six registrations/genesis remain unchanged and are never reassembled.
    registration=fleet.init_identity(joined,name,home,binary)
    output.mkdir(parents=True,mode=0o700)
    folder=output/name; folder.mkdir(mode=0o700)
    p=fleet.ports(joined,name)
    (folder/'genesis.json').write_bytes(network.bounded(Path(reference)/'genesis.json'))
    (folder/'config.toml').write_bytes(network.bounded(home/'config/config.toml'))
    dial=','.join(f"{provider['node_id']}@{ref['network_profile']['endpoints'][provider['name']]['host']}:{ref['network_profile']['endpoints'][provider['name']]['port']}" for provider in public['providers'])
    fleet.set_toml(folder/'config.toml','',{'proxy_app':json.dumps(f"127.0.0.1:{p['abci']}"),'abci':'"grpc"','moniker':json.dumps(name),'log_level':'"*:error,statesync:info"'})
    fleet.set_toml(folder/'config.toml','rpc',{'laddr':json.dumps(f"tcp://127.0.0.1:{p['rpc']}"),'unsafe':'false','max_open_connections':'32'})
    fleet.set_toml(folder/'config.toml','p2p',{'laddr':json.dumps(f"tcp://{spec['host']}:{p['p2p']}"),'external_address':'""',
        'persistent_peers':json.dumps(dial),'seeds':'""','pex':'false','addr_book_strict':'false','allow_duplicate_ip':'true',
        'max_num_inbound_peers':'16','max_num_outbound_peers':'16','persistent_peers_max_dial_period':'"5s"'})
    fleet.set_toml(folder/'config.toml','instrumentation',{'prometheus':'true','prometheus_listen_addr':json.dumps(f"127.0.0.1:{p['metrics']}" )})
    fleet.set_toml(folder/'config.toml','statesync',{'enable':'false'})
    artifacts={'rpc-nginx.conf':fleet.gateway(joined,spec),'docker-compose.yml':fleet.compose(spec,True),
               'firewall.nft':fleet.firewall(joined,spec),**fleet.units(joined,spec,str(root))}
    for filename,text in artifacts.items(): (folder/filename).write_text(text)
    m={'format':1,'schema':3,'chain_id':ref['chain_id'],'node':spec,'ports':p,'home_root':str(root),
       'application_home':str(root/ref['chain_id']/'apps'/name),'inventory_sha256':registration['inventory_sha256'],
       'genesis_sha256':ref['genesis_sha256'],'binary_sha256':fleet.binary_identity(binary),'source_commit':fleet.SOURCE_COMMIT,
       'registration':registration,'peers':peers,'files':{f:fleet.digest_file(folder/f) for f in ('config.toml','genesis.json',*artifacts)}}
    if m['binary_sha256']!=ref['binary_sha256']: raise ValueError('follower binary differs from approved fleet')
    fleet.write(folder/'node.json',m)
    # Existing configure checks the fresh identity and public bundle; it does NOT
    # rewrite existing node histories or introduce the follower into validators.
    fleet.configure(home,folder,fleet.digest_file(folder/'node.json'))
    m=fleet.read(home/'node.json')
    m['network_profile']=deepcopy(ref['network_profile']); m['network_profile']['endpoints'][name]=None
    m['bootstrap_profile']=public; m['admission_inventory']=joined
    shutil.copyfile(ca,home/'bootstrap-ca.pem'); (home/'bootstrap-ca.pem').chmod(0o600)
    (home/'bootstrap-profile.json').write_bytes(public_raw); (home/'bootstrap-profile.json').chmod(0o600)
    (home/'empty-trust-directory').mkdir(mode=0o700)
    for filename in ('bootstrap-ca.pem','bootstrap-profile.json'): m['files'][filename]=fleet.digest_file(home/filename)
    helper={**m,'_original_firewall':(home/'firewall.nft').read_text()}
    (home/'firewall.nft').write_text(network.firewall_text(helper)); m['files']['firewall.nft']=fleet.digest_file(home/'firewall.nft')
    fleet.write(home/'node.json',m)
    fleet.write(output/'admission-inventory.json',joined)
    fleet.write(output/'registration.json',registration)
    return {'home':str(home),'node':name,'ports':p,'manifest_sha256':fleet.digest_file(home/'node.json'),
            'genesis_unchanged':True,'added_validator':False,'private_keys_exported':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['create','capture','configure','complete'])
    parser.add_argument('--root',type=Path)
    parser.add_argument('--inventory',type=Path)
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--node')
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--profile-sha256')
    parser.add_argument('--ca',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--home',type=Path)
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--authority-private',type=Path)
    parser.add_argument('--resume-uninitialized',action='store_true',help='configure only: explicitly reuse a stopped entirely empty app DB; never resets history')
    parser.add_argument('--binary',type=Path,default=fleet.WORKSPACE/'.tools/bin/cometbft')
    args=parser.parse_args()
    if args.resume_uninitialized and args.command!='configure':
        parser.error('--resume-uninitialized is configure only')
    fields={'create':('root','inventory','reference','node','profile','profile_sha256','output'),
            'capture':('home','profile','profile_sha256','authority_private','checkpoint'),
            'configure':('home','profile','profile_sha256','checkpoint'),'complete':('home',)}[args.command]
    if any(getattr(args,f) is None for f in fields): parser.error('missing explicit fields: '+', '.join(fields))
    if args.command=='create': result=create(args.root,args.inventory,args.reference,args.node,args.profile,args.profile_sha256,args.ca,args.output,args.binary)
    elif args.command=='complete': result=bootstrap.complete(args.home,args.ca)
    else:
        public,_=network.approved(args.profile,args.profile_sha256)
        result=bootstrap.capture(args.home,public,args.ca,args.authority_private,args.checkpoint) if args.command=='capture' else bootstrap.configure(args.home,args.checkpoint,public,args.ca,resume_uninitialized=args.resume_uninitialized)
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
