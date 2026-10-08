#!/usr/bin/env python3
"""Local operator controls ONLY the installed home-contained multisite fleet."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request


def selected(root,chain,names):
    from computechain.scripts.install_multisite import safe_root
    root=safe_root(root)
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,39}',chain): raise ValueError('unsafe chain name')
    folder=root/chain/'nodes'
    if folder.is_symlink() or (root/chain).is_symlink(): raise ValueError('fleet paths must not be symlinks')
    available={p.name:p for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and (p/'node.json').is_file()}
    if not available: raise ValueError('no installed nodes')
    if names and (len(set(names))!=len(names) or set(names)-set(available)): raise ValueError('choose distinct installed node names')
    result=[]
    for name in names or sorted(available):
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,23}',name): raise ValueError('unsafe node name')
        manifest=json.loads((available[name]/'node.json').read_text())
        if manifest.get('home_root')!=str(root) or manifest['chain_id']!=chain or manifest['node']['name']!=name:
            raise ValueError('installed manifest identity mismatch')
        result.append((name,available[name],manifest))
    return result


def main():
    # Runtime deployment lives at HOME/computechain-node/runtime/computechain/scripts/.
    runtime=Path(__file__).resolve().parents[2]
    import sys
    sys.path.insert(0,str(runtime))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','up','down','logs'])
    parser.add_argument('nodes',nargs='*')
    parser.add_argument('--root',type=Path,default=runtime.parent)
    parser.add_argument('--chain',default='cpc-multisite-devnet-1')
    args=parser.parse_args()
    if os.geteuid()!=0: parser.error('run with sudo: operator access to private manifests is required')
    rows=selected(args.root,args.chain,args.nodes)
    for name,home,manifest in rows:
        prefix='cpc-'+args.chain+'-'+name
        if args.command=='up':
            if not args.nodes and 'bootstrap_profile' in manifest and 'bootstrap_completed' not in manifest:
                print(json.dumps({'node':name,'skipped':'signed bootstrap must be explicitly started by node name'}))
                continue
            # The actual on-host doctor is always required before an operator start.
            from computechain.scripts.multisite import doctor
            doctor(home,args.root/'runtime/.tools/bin/cometbft')
            subprocess.run(['systemctl','start',*[prefix+'-'+p+'.service' for p in ('app','engine','readrpc','rpc')]],check=True)
            extra=prefix+'-bootstrap-read.service'
            if subprocess.run(['systemctl','show',extra,'-p','LoadState','--value'],capture_output=True,text=True).stdout.strip()=='loaded':
                subprocess.run(['systemctl','start',extra],check=True)
        elif args.command=='down':
            extra=prefix+'-bootstrap-read.service'
            if subprocess.run(['systemctl','show',extra,'-p','LoadState','--value'],capture_output=True,text=True).stdout.strip()=='loaded':
                subprocess.run(['systemctl','stop',extra],check=True)
            subprocess.run(['systemctl','stop',*[prefix+'-'+p+'.service' for p in ('rpc','readrpc','engine','app')]],check=True)
        elif args.command=='logs':
            subprocess.run(['journalctl','--no-pager','-n','40','-u',prefix+'-engine.service','-u',prefix+'-app.service'],check=True)
        else:
            result={'node':name,'host':manifest['node']['host'],'role':manifest['node']['role']}
            for part in ('engine','app','readrpc','rpc'):
                result[part]=subprocess.run(['systemctl','is-active',prefix+'-'+part+'.service'],capture_output=True,text=True).stdout.strip()
            result['resources']=subprocess.check_output(['systemctl','show',prefix+'.slice','-p','MemoryCurrent','-p','CPUUsageNSec'],text=True).splitlines()
            port=manifest['ports']['rpc']
            if type(port) is not int or not 1024<=port<=65535: raise ValueError('invalid native loopback port')
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f'http://127.0.0.1:{port}/status',timeout=2) as response: raw=response.read(65537)
                if len(raw)>65536: raise ValueError('oversized status response')
                native=json.loads(raw)['result']
                if native['node_info']['id']!=manifest['registration']['node_id'] or native['node_info']['network']!=args.chain:
                    raise ValueError('native node identity mismatch')
                result['height']=native['sync_info']['latest_block_height']; result['catching_up']=native['sync_info']['catching_up']
            except Exception as exc: result['rpc_error']=str(exc)
            print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
