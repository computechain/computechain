#!/usr/bin/env python3
"""LOCAL-only fleet preparation/native RPC gateway/state-sync exercise; not multi-host proof."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import urllib.error
import urllib.request

REPO=Path(__file__).resolve().parents[1]
WORKSPACE=REPO.parent
sys.path.insert(0,str(WORKSPACE))
from computechain.scripts import multisite as fleet
from computechain.scripts.comet_devnet import Network,write,read,wait_for,height,set_toml,rpc
from computechain.blockchain.comet.transaction import sign_transfer
from computechain.blockchain.comet.economics import UNIT


def run(root,base):
    root=Path(root).resolve()
    if root.exists(): raise ValueError('choose a NEW verification directory; existing data preserved')
    inventory=read(REPO / 'deploy/multisite.example.json')
    inventory['chain_id']='cpc-fleet-loopback-verification-1'
    inventory['base_port']=base
    fleet.inventory(inventory)
    binary=WORKSPACE / '.tools/bin/cometbft'
    # Explicitly reserve the whole exercise range before generating any keys.
    reservations=[]
    try:
        for i in range(6):
            for k in range(6):
                sock=socket.socket(); reservations.append(sock); sock.bind(('127.0.0.1',base+i*10+k))
    finally:
        for sock in reservations: sock.close()
    root.mkdir(parents=True,mode=0o700)
    records=[]
    for spec in inventory['nodes']:
        records.append(fleet.init_identity(inventory,spec['name'],root / spec['name'],binary))
    prepared=fleet.assemble(inventory,records,root / 'public-bundles',records[0]['owner'],binary)
    nodes=[]
    for spec in inventory['nodes']:
        home=root / spec['name']; nodes.append(str(home))
        fleet.configure(home,root / 'public-bundles' / spec['name'],prepared['manifest_sha256'][spec['name']])
        # Test fixture ONLY: logical-site addresses are replaced with loopback.
        # Production run-engine/doctor remains deliberately untested without the hosts.
        peers=','.join(f"{records[j]['node_id']}@127.0.0.1:{base+j*10}" for j in range(6) if records[j]['name']!=spec['name'])
        p=fleet.ports(inventory,spec['name'])
        set_toml(home / 'config/config.toml','p2p',{'laddr':json.dumps(f"tcp://127.0.0.1:{p['p2p']}"),'external_address':json.dumps(f"127.0.0.1:{p['p2p']}"),'persistent_peers':json.dumps(peers)})
    network={'schema':3,'chain_id':inventory['chain_id'],'base_port':base,'binary':str(binary),'nodes':nodes,
        'genesis_sha256':prepared['genesis_sha256']}
    write(root / 'network.json',network); write(root / 'processes.json',{})
    net=Network(root); containers=[]
    report={'local_only':True,'real_multi_host_verified':False,'scenarios':{}}
    def record(name,value):
        report['scenarios'][name]=value; write(root / 'verification.json',report); print(name+': '+json.dumps(value),flush=True)
    def get_gateway(i,method):
        with urllib.request.urlopen(f'http://127.0.0.1:{base+i*10+4}/{method}',timeout=3) as response: return json.load(response)['result']
    try:
        for i in range(4): net.start_node(i)
        wait_for('fleet validators producing',lambda:min(height(network,i) for i in range(4))>=8,60)
        net.start_node(4)
        wait_for('fleet full sync',lambda:height(network,4)>=8,60)
        record('fleet_prepared_and_full_sync',net.agree(list(range(5)),6))
        private=bytes.fromhex((Path(nodes[0]) / 'owner-private.hex').read_text())
        before=net.state(0)['accounts'][records[1]['owner']]['balance']
        nonce=net.state(0)['accounts'][records[0]['owner']]['nonce']
        sent=net.submit(sign_transfer(private,inventory['chain_id'],records[1]['owner'],UNIT,nonce),UNIT)
        record('signed_transfer',sent)
        for i in (0,1):
            net.spawn(f'readrpc{i}',[sys.executable,'-m','computechain.scripts.rpc_read_gateway',
                '--listen',f'127.0.0.1:{base+i*10+5}','--upstream',f'http://127.0.0.1:{base+i*10+1}'])
            def adapter_ready():
                with socket.create_connection(('127.0.0.1',base+i*10+5),timeout=1): return True
            wait_for('JSON-RPC read adapter',adapter_ready,10)
            # Real pinned Nginx with the generated gateway, confined to loopback for QA.
            fake=json.loads(json.dumps(inventory))
            for spec in fake['nodes']: spec['host']='127.0.0.1'
            fake['readers']=[]
            conf=root / f'gateway{i}.conf'; conf.write_text(fleet.gateway(fake,fake['nodes'][i])); conf.chmod(0o644)
            container='cpc-fleet-verify-'+hashlib.sha256(str(root).encode()).hexdigest()[:10]+'-'+str(i)
            containers.append(container)
            subprocess.run(['docker','run','-d','--name',container,'--network','host','--user','101:101','--read-only',
                '--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','128m','--pids-limit','64',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=16m,mode=1777','-v',f'{conf}:/etc/nginx/nginx.conf:ro',
                '--entrypoint','nginx',fleet.NGINX,'-g','daemon off;'],check=True,stdout=subprocess.DEVNULL)
            wait_for('native RPC gateway',lambda:get_gateway(i,'status')['node_info']['network']==inventory['chain_id'],10)
            for path,method,expected in [('/broadcast_tx_commit?tx=0x00','GET',404),('/abci_query?path=/state','GET',404),('/','POST',413)]:
                try:
                    urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{base+i*10+4}'+path,method=method),timeout=3)
                    raise RuntimeError('privileged gateway route was accessible')
                except urllib.error.HTTPError as exc:
                    if exc.code!=expected: raise
        record('native_read_only_rpc_gateways',{'nodes':[0,1],'privileged_requests_rejected':True})
        checkpoint=max(1,height(network,0)-3)
        digest=rpc(network,0,'block',height=checkpoint)['block_id']['hash']
        set_toml(Path(nodes[5]) / 'config/config.toml','statesync',{'enable':'true',
            'rpc_servers':json.dumps(f'http://127.0.0.1:{base+4},http://127.0.0.1:{base+14}'),
            'trust_height':str(checkpoint),'trust_hash':json.dumps(digest),'trust_period':'"30s"','discovery_time':'"5s"',
            'chunk_request_timeout':'"5s"','chunk_fetchers':'2','max_snapshot_chunks':'64'})
        target=height(network,0)
        net.start_node(5)
        wait_for('native state sync via restricted RPC',lambda:height(network,5)>=target,90)
        if 'Snapshot restored' not in (root / 'engine5.log').read_text(errors='replace'):
            raise RuntimeError('native restore not proven; block-sync fallback is not success')
        def agreement():
            h=height(network,5)-1
            return net.agree(list(range(6)),h) if h>=target else False
        record('native_state_sync_through_gateways',wait_for('six-node commitments',agreement,30))
        balances=[net.state(i)['accounts'][records[1]['owner']]['balance'] for i in range(6)]
        if balances!=[before+UNIT]*6: raise RuntimeError('transfer balances differ after full/state sync')
        record('same_transfer_state',{'balances':balances,'nonce':net.state(5)['accounts'][records[0]['owner']]['nonce']})
        report['passed']=True
    except Exception as exc:
        report.update(passed=False,error=str(exc)); raise
    finally:
        for i in (0,1): net.stop(f'readrpc{i}')
        net.down()
        for container in containers:
            subprocess.run(['docker','rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        report['processes_stopped']=not read(root / 'processes.json')
        write(root / 'verification.json',report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir',type=Path,required=True)
    parser.add_argument('--base-port',type=int,default=31600)
    args=parser.parse_args(); run(args.dir,args.base_port)


if __name__=='__main__': main()
