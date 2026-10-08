#!/usr/bin/env python3
"""Owned LOOPBACK native HTTPS state-sync exercise; not real WAN deployment proof."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import ssl
import sys
import threading
from computechain.scripts import multisite as fleet
from computechain.scripts import bootstrap_pki as pki
from computechain.scripts import bootstrap_protocol as protocol
from computechain.scripts import bootstrap_read_service as tls
from computechain.scripts import signed_checkpoint as signed
from computechain.scripts.comet_devnet import Network,write,read,wait_for,height,set_toml
from computechain.blockchain.comet.transaction import sign_transfer
from computechain.blockchain.comet.economics import UNIT


def run(root,base):
    root=fleet.outside_git(root)
    if root.exists(): raise ValueError('NEW exercise directory required')
    reservations=[]
    try:
        for i in range(6):
            for j in range(4):
                s=socket.socket(); s.bind(('127.0.0.1',base+i*10+j)); reservations.append(s)
        for i in range(2):
            s=socket.socket(); s.bind((f'127.0.0.{i+2}',base+i*10+6)); reservations.append(s)
    finally:
        for s in reservations: s.close()
    root.mkdir(mode=0o700)
    inv=read(fleet.REPO/'deploy/multisite.example.json'); inv['chain_id']='cpc-tls-bootstrap-qa-1'; inv['base_port']=base
    binary=fleet.WORKSPACE/'.tools/bin/cometbft'
    registrations=[fleet.init_identity(inv,n['name'],root/n['name'],binary) for n in inv['nodes']]
    prepared=fleet.assemble(inv,registrations,root/'public-bundles',registrations[0]['owner'],binary)
    nodes=[]
    for i,spec in enumerate(inv['nodes']):
        home=root/spec['name']; nodes.append(str(home))
        fleet.configure(home,root/'public-bundles'/spec['name'],prepared['manifest_sha256'][spec['name']])
        # Explicit QA fixture only: all network identities/data are new and local.
        peers=','.join(f"{r['node_id']}@127.0.0.1:{base+j*10}" for j,r in enumerate(registrations) if j!=i)
        set_toml(home/'config/config.toml','p2p',{'laddr':json.dumps(f'tcp://127.0.0.1:{base+i*10}'),'external_address':json.dumps(f'127.0.0.1:{base+i*10}'),'persistent_peers':json.dumps(peers)})
        m=read(home/'node.json'); m['files']['config.toml']=fleet.digest_file(home/'config/config.toml')
        m['application_home']=str(home/'application'); write(home/'node.json',m)
    config={'schema':3,'chain_id':inv['chain_id'],'base_port':base,'binary':str(binary),'nodes':nodes,'genesis_sha256':prepared['genesis_sha256']}
    write(root/'network.json',config); write(root/'processes.json',{})
    net=Network(root); servers=[]; threads=[]
    report={'local_only':True,'real_wan_verified':False,'scenarios':{}}
    def record(name,value):
        report['scenarios'][name]=value; write(root/'verification.json',report); print(name+': '+json.dumps(value),flush=True)
    try:
        for i in range(4): net.start_node(i)
        wait_for('QA blocks',lambda:height(config,0)>=12,50)
        private=bytes.fromhex((Path(nodes[0])/'owner-private.hex').read_text())
        state=net.state(0); recipient=registrations[1]['owner']; before=state['accounts'][recipient]['balance']
        tx=net.submit(sign_transfer(private,inv['chain_id'],recipient,UNIT,state['accounts'][registrations[0]['owner']]['nonce']),UNIT)
        record('signed_transfer',tx)
        ca=pki.ca_init(root/'pki'); authority=signed.key_init(root/'authority.hex')
        providers=[]
        for i in (0,1):
            host=f'127.0.0.{i+2}'; csr=pki.identity_init(root/f'tls{i}',f'provider-{i}',host)
            cert=pki.issue(root/'pki',csr,host,root/f'cert{i}.pem')
            server=tls.TLSServer({'format':1,'listen':f'{host}:{base+i*10+6}','upstream':f'http://127.0.0.1:{base+i*10+1}','allowed_sources':['127.0.0.1']},cert,root/f'tls{i}/tls-private.pem')
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start(); servers.append(server); threads.append(thread)
            providers.append({'name':registrations[i]['name'],'node_id':registrations[i]['node_id'],'location':inv['nodes'][i]['location'],
                'url':f'https://{host}:{base+i*10+6}','certificate_sha256':hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()})
        # Logical locations need distinct labels for this local fixture; no claim
        # that two loopback listeners are independent physical failure domains.
        providers[1]['location']='qa-site-b'
        profile={'format':1,'chain_id':inv['chain_id'],'genesis_sha256':prepared['genesis_sha256'],
                 'ca_sha256':hashlib.sha256(ca.read_bytes()).hexdigest(),'operator_public_key':authority['public_key'],'providers':providers}
        target=Path(nodes[5]); shutil.copyfile(ca,target/'bootstrap-ca.pem')
        m=read(target/'node.json'); m['bootstrap_profile']=profile; m['files']['bootstrap-ca.pem']=fleet.digest_file(target/'bootstrap-ca.pem'); write(target/'node.json',m)
        checkpoint=root/'signed-checkpoint.json'
        captured=protocol.capture(target,profile,ca,root/'authority.hex',checkpoint,local_qa=True)
        configured=protocol.configure(target,checkpoint,profile,ca,local_qa=True)
        record('operator_signed_tls_checkpoint',{'height':captured['checkpoint']['height'],'signature_verified':configured['signed_checkpoint_verified']})
        net.spawn('app5',[sys.executable,'-m','computechain.blockchain.comet.node','--datadir',str(target/'application'),
                        '--chain-id',inv['chain_id'],'--listen',f'127.0.0.1:{base+52}','--snapshot-interval','5'])
        def app_ready():
            with socket.create_connection(('127.0.0.1',base+52),timeout=1): return True
        wait_for('fresh app',app_ready,10)
        (target/'empty-trust-directory').mkdir()
        # Native Go HTTP client: pinned CA only, proxy bypass local to this process.
        engine=net.spawn('engine5',['env','SSL_CERT_FILE='+str(ca),'SSL_CERT_DIR='+str(target/'empty-trust-directory'),'NO_PROXY=*','HTTPS_PROXY=','HTTP_PROXY=',
                              str(binary),'start','--home',str(target)])
        initial=height(config,0)
        def restored():
            if engine.poll() is not None: raise ValueError('native TLS engine exited: '+(root/'engine5.log').read_text(errors='replace')[-1800:])
            return height(config,5)>=initial
        wait_for('native HTTPS state sync',restored,60)
        logs=(root/'engine5.log').read_text(errors='replace')
        if 'Snapshot restored' not in logs: raise RuntimeError('native snapshot restore not proven')
        h=height(config,5)-1
        record('native_tls_restore',net.agree([0,1,2,3,5],h))
        if net.state(5)['accounts'][recipient]['balance']!=before+UNIT: raise RuntimeError('restored account balance differs')
        record('restored_state',{'balance':net.state(5)['accounts'][recipient]['balance'],'nonce':net.state(5)['accounts'][registrations[0]['owner']]['nonce']})
        report['passed']=True
    except Exception as exc:
        report.update(passed=False,error=str(exc)); raise
    finally:
        net.down()
        for server in servers: server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=5)
        report['processes_stopped']=not read(root/'processes.json'); write(root/'verification.json',report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir',type=Path,required=True); parser.add_argument('--base-port',type=int,default=32600)
    args=parser.parse_args(); run(args.dir,args.base_port)


if __name__=='__main__': main()
