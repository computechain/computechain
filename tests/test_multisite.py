"""Offline fleet preparation: only scratch identities/public bundles, no SSH/network changes."""
from copy import deepcopy
import base64
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
import time

import pytest

from computechain.scripts import multisite as fleet
from computechain.blockchain.comet.staking import initial_state
from computechain.blockchain.comet.economics import UNIT

BINARY=fleet.WORKSPACE / '.tools/bin/cometbft'
EXAMPLE=fleet.REPO / 'deploy/multisite.example.json'


@pytest.fixture
def inv(): return fleet.read(EXAMPLE)


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    if not BINARY.exists(): pytest.skip('pinned native Comet binary required for fleet integration')
    root=tmp_path_factory.mktemp('public-fleet-preparation')
    value=fleet.read(EXAMPLE)
    records=[]
    for node in value['nodes']:
        records.append(fleet.init_identity(value,node['name'],root / node['name'],BINARY))
    output=root / 'public-bundles'
    result=fleet.assemble(value,records,output,records[0]['owner'],BINARY)
    return root,value,records,output,result


def test_topology_detects_actual_site_and_host_quorum(inv):
    p=fleet.topology(inv)
    assert p['total_power']==40000
    assert not p['locations']['site-a']['can_finalize']
    assert p['locations']['site-b']['can_finalize'] and p['locations']['site-c']['can_finalize']
    assert all(r['can_finalize'] for r in p['hosts'].values())
    assert not p['all_location_failures_tolerated']
    inv['nodes'][1]['host']=inv['nodes'][0]['host']
    inv['nodes'][1]['machine']=inv['nodes'][0]['machine']
    assert not fleet.topology(inv)['hosts'][inv['nodes'][0]['host']]['can_finalize']


def test_two_vm_addresses_on_one_machine_are_one_failure_domain(inv):
    inv['nodes'][1]['machine']=inv['nodes'][0]['machine']
    report=fleet.topology(inv)
    assert not report['machines'][inv['nodes'][0]['machine']]['can_finalize']
    assert report['hosts'][inv['nodes'][0]['host']]['can_finalize']


def test_physical_machine_cannot_span_locations(inv):
    inv['nodes'][2]['machine']=inv['nodes'][0]['machine']
    with pytest.raises(ValueError,match='span'): fleet.inventory(inv)


def test_generated_secrets_and_bundles_cannot_be_created_inside_git(tmp_path):
    repo=tmp_path / 'checkout'; repo.mkdir(); (repo / '.git').mkdir()
    with pytest.raises(ValueError,match='outside Git'):
        fleet.outside_git(repo / 'new-node')
    assert not (repo / 'new-node').exists()


@pytest.mark.parametrize('fault',['public','wrong-subnet','network','broadcast','overlap','name','duplicate','bool-stake',
    'unknown-role','full-power','port','bool-port','password','same-witness-site','same-witness-host','single-site',
    'public-reader','wildcard-reader','duplicate-reader'])
def test_unsafe_inventory_rejected_before_writes(inv,fault):
    if fault=='public': inv['nodes'][0]['host']='78.29.35.87'
    if fault=='wrong-subnet': inv['nodes'][0]['host']='192.168.2.201'
    if fault=='network': inv['nodes'][0]['host']='192.168.0.0'
    if fault=='broadcast': inv['nodes'][0]['host']='192.168.0.255'
    if fault=='overlap': inv['locations']['site-b']='192.168.0.0/25'
    if fault=='name': inv['nodes'][0]['name']='../node'
    if fault=='duplicate': inv['nodes'][1]['name']=inv['nodes'][0]['name']
    if fault=='bool-stake': inv['nodes'][0]['stake_cpc']=True
    if fault=='unknown-role': inv['nodes'][0]['role']='root'
    if fault=='full-power': inv['nodes'][4]['stake_cpc']=1000
    if fault=='port': inv['base_port']=65530
    if fault=='bool-port': inv['base_port']=True
    if fault=='password': inv['password']='must-not-be-in-inventory'
    if fault=='same-witness-site':
        inv['nodes'][5].update(location='site-b',host='192.168.1.203')
        inv['nodes'][5]['machine']='host-b3'
        inv['nodes'][3]['witness']=False
    if fault=='same-witness-host': inv['nodes'][5].update(location='site-b',host='192.168.1.202')
    if fault=='same-witness-host':
        inv['nodes'][2]['witness']=False
        inv['nodes'][3]['witness']=False
    if fault=='single-site':
        for i in (2,3): inv['nodes'][i].update(location='site-a',host=f'192.168.0.{210+i}',machine=f'host-aa{i}')
    if fault=='public-reader': inv['readers']=['8.8.8.8']
    if fault=='wildcard-reader': inv['readers']=['0.0.0.0']
    if fault=='duplicate-reader': inv['readers']*=2
    with pytest.raises((ValueError,TypeError)): fleet.inventory(inv)


def test_node_identity_is_unique_and_no_private_data_exported(prepared):
    root,value,records,output,result=prepared
    assert len({r['consensus_key'] for r in records})==6
    assert len({r['node_id'] for r in records})==6
    assert result['private_keys_exported'] is False
    for spec,r in zip(value['nodes'],records):
        home=root / spec['name']
        assert (home / 'owner-private.hex').stat().st_mode & 0o777==0o600
        assert set(r)==fleet.REG_FIELDS
        private_values=[(home / 'owner-private.hex').read_text()]
        for filename in ('node_key.json','priv_validator_key.json'):
            assert (home / 'config' / filename).stat().st_mode & 0o777==0o600
            private_values.append(fleet.read(home / 'config' / filename)['priv_key']['value'])
        for f in output.rglob('*'):
            if f.is_file():
                text=f.read_text()
                assert all(v not in text for v in private_values),f.name
    assert not list(output.rglob('*.hex'))
    assert not list(output.rglob('priv_validator_key.json'))


@pytest.mark.parametrize('fault',['signature','node-id','owner','inventory','chain','duplicate','extra'])
def test_bad_registration_rejected(prepared,fault):
    _,value,records,_,_=prepared
    records=deepcopy(records)
    if fault=='signature': records[0]['consensus_signature']='00'*64
    if fault=='node-id': records[0]['node_id']='0'*40
    if fault=='owner': records[0]['owner']=records[1]['owner']
    if fault=='inventory': records[0]['inventory_sha256']='f'*64
    if fault=='chain': records[0]['chain_id']='wrong-chain'
    if fault=='duplicate': records[1]=deepcopy(records[0])
    if fault=='extra': records[0]['private_key']='not-allowed'
    with pytest.raises(ValueError): fleet.registrations(value,records)


def test_genesis_config_and_gateway_boundaries(prepared):
    _,value,_,output,result=prepared
    genesis=fleet.read(output / 'genesis.json')
    state=initial_state(value['chain_id'],genesis['app_state'])
    assert state['supply']==1_000_000*UNIT
    assert len(genesis['validators'])==4 and sum(int(v['power']) for v in genesis['validators'])==40000
    for spec in value['nodes']:
        folder=output / spec['name']
        assert fleet.digest_file(folder / 'genesis.json')==result['genesis_sha256']
        config=tomllib.loads((folder / 'config.toml').read_text())
        p=fleet.ports(value,spec['name'])
        assert config['proxy_app']==f"127.0.0.1:{p['abci']}" and config['abci']=='grpc'
        assert config['rpc']['laddr']==f"tcp://127.0.0.1:{p['rpc']}" and not config['rpc']['unsafe']
        assert config['p2p']['laddr']==f"tcp://{spec['host']}:{p['p2p']}" and not config['p2p']['pex']
        assert len(config['p2p']['persistent_peers'].split(','))==5
        assert not config['statesync']['enable']
        gateway=(folder / 'rpc-nginx.conf').read_text()
        assert 'deny all;' in gateway and '^(GET|HEAD|POST)$' in gateway
        assert 'location = /commit ' in gateway and 'location = /validators ' in gateway
        assert 'location = /metrics ' in gateway
        assert 'broadcast_tx' not in gateway and 'abci_query' not in gateway and '/websocket' not in gateway
        assert f'127.0.0.1:{p["abci"]}' not in gateway
        assert 'flush ruleset' not in (folder / 'firewall.nft').read_text()
        assert 'docker.sock' not in (folder / 'docker-compose.yml').read_text()


def test_configure_checks_approved_hash_and_preserves_keys(prepared,tmp_path):
    root,value,_,output,result=prepared
    spec=value['nodes'][0]
    home=tmp_path / 'home'
    shutil.copytree(root / spec['name'],home)
    before={name:(home / 'config' / name).read_bytes() for name in ('node_key.json','priv_validator_key.json')}
    with pytest.raises(ValueError,match='SHA256'):
        fleet.configure(home,output / spec['name'],'f'*64)
    assert not (home / 'node.json').exists()
    fleet.configure(home,output / spec['name'],result['manifest_sha256'][spec['name']])
    assert fleet.checked_home(home)['node']['name']==spec['name']
    assert all((home / 'config' / n).read_bytes()==v for n,v in before.items())
    with pytest.raises(ValueError,match='local identity'):
        fleet.configure(home,output / value['nodes'][1]['name'],result['manifest_sha256'][value['nodes'][1]['name']])
    (home / 'application').mkdir()
    (home / 'application/application.sqlite').write_bytes(b'preserve-real-data')
    with pytest.raises(ValueError,match='fresh history'):
        fleet.configure(home,output / spec['name'],result['manifest_sha256'][spec['name']])
    assert (home / 'application/application.sqlite').read_bytes()==b'preserve-real-data'


def test_modified_artifact_or_key_cannot_start(prepared,tmp_path):
    root,value,_,output,result=prepared
    name=value['nodes'][0]['name']
    home=tmp_path / 'home'; shutil.copytree(root / name,home)
    fleet.configure(home,output / name,result['manifest_sha256'][name])
    (home / 'config/config.toml').write_text('proxy_app="0.0.0.0:26658"')
    with pytest.raises(ValueError,match='artifact changed'): fleet.checked_home(home)


def test_doctor_needs_assigned_ip_routes_and_clock(prepared,tmp_path,monkeypatch):
    root,value,_,output,result=prepared
    name=value['nodes'][0]['name']; home=tmp_path / 'home'; shutil.copytree(root / name,home)
    fleet.configure(home,output / name,result['manifest_sha256'][name])
    assigned=value['nodes'][0]['host']
    def command(args,**kwargs):
        if args[0]=='timedatectl': return 'yes\n'
        if 'addr' in args: return json.dumps([{'addr_info':[{'local':assigned}]}])
        return json.dumps([{'dev':'overlay-route'}])
    monkeypatch.setattr(fleet.subprocess,'check_output',command)
    assert fleet.doctor(home,BINARY)['clock_synchronized']
    assigned='192.168.0.250'
    with pytest.raises(ValueError,match='not assigned'): fleet.doctor(home,BINARY)


def test_existing_identity_and_bundle_are_never_overwritten(prepared):
    root,value,records,output,_=prepared
    with pytest.raises(ValueError,match='NEW home'):
        fleet.init_identity(value,value['nodes'][0]['name'],root / value['nodes'][0]['name'],BINARY)
    with pytest.raises(ValueError,match='no overwrite'):
        fleet.assemble(value,records,output,records[0]['owner'],BINARY)


def test_native_transport_id_matches_registration(prepared):
    root,value,records,_,_=prepared
    for spec,r in zip(value['nodes'],records):
        actual=subprocess.check_output([str(BINARY),'show-node-id','--home',str(root / spec['name'])],text=True).strip()
        assert actual==r['node_id']


def test_service_templates_separate_app_keys_and_root_operations(prepared):
    _,value,_,output,_=prepared
    spec=value['nodes'][0]; folder=output / spec['name']
    app=next(folder.glob('*-app.service')).read_text()
    engine=next(folder.glob('*-engine.service')).read_text()
    rpc=next(folder.glob('*-rpc.service')).read_text()
    assert 'User=cpa-'+spec['name'] in app and 'User=cpc-'+spec['name'] in engine
    assert '/var/lib/computechain-app/' in app and 'InaccessiblePaths=/var/lib/computechain/' in app
    assert '--file /etc/computechain/' in rpc
    assert '--file /var/lib/computechain/' not in rpc


def test_home_profile_has_shared_resource_caps_and_private_mounts(inv):
    spec=inv['nodes'][2]
    root='/home/pc205/computechain-node'
    result=fleet.units(inv,spec,root)
    app=next(v for k,v in result.items() if k.endswith('-app.service'))
    engine=next(v for k,v in result.items() if k.endswith('-engine.service'))
    reader=next(v for k,v in result.items() if k.endswith('-readrpc.service'))
    rpc=next(v for k,v in result.items() if k.endswith('-rpc.service'))
    limits=next(v for k,v in result.items() if k.endswith('.slice'))
    home=f"{root}/{inv['chain_id']}/nodes/{spec['name']}"
    application=f"{root}/{inv['chain_id']}/apps/{spec['name']}"
    assert 'ProtectHome=tmpfs' in app and f'BindPaths={application}' in app
    assert f'BindPaths={home}' not in app and f'InaccessiblePaths=-{home}' in app
    assert f'BindPaths={home}' in engine and 'GOMEMLIMIT=192MiB' in engine
    assert 'BindPaths=' not in reader and f'BindReadOnlyPaths={root}/runtime' in reader
    assert 'CPUQuota=30%' in limits and 'MemoryMax=448M' in limits
    assert '--file /etc/computechain/' in rpc and f'--file {root}' not in rpc
    assert 'cpus: 0.10' in fleet.compose(spec,True)


@pytest.mark.parametrize('root',['/tmp/computechain-node','/root/../computechain-node','/root/computechain-node x','/home/pc205'])
def test_home_profile_rejects_unscoped_paths(inv,root):
    with pytest.raises(ValueError,match='home root'):
        fleet.units(inv,inv['nodes'][0],root)


def test_mixed_home_profiles_are_bound_to_each_approved_manifest(prepared,tmp_path):
    _,value,records,_,_=prepared
    roots={n['name']:('/home/pc205/computechain-node' if n['location']=='site-b' else '/root/computechain-node') for n in value['nodes']}
    output=tmp_path/'mixed-profile'
    fleet.assemble(value,records,output,records[0]['owner'],BINARY,roots)
    for node in value['nodes']:
        manifest=fleet.read(output/node['name']/'node.json')
        assert manifest['home_root']==roots[node['name']]
        assert manifest['application_home']==f"{roots[node['name']]}/{value['chain_id']}/apps/{node['name']}"
        assert len([f for f in manifest['files'] if f.endswith('.slice')])==1


def test_finish_partial_registration_keeps_keys_and_refuses_overwrite(prepared,tmp_path):
    root,value,records,_,_=prepared
    spec=value['nodes'][0]
    home=tmp_path/'unfinished'
    shutil.copytree(root/spec['name'],home)
    (home/'registration.json').unlink()  # owned scratch fixture only
    before={str(p.relative_to(home)):p.read_bytes() for p in home.rglob('*') if p.is_file()}
    record=fleet.register_identity(value,spec['name'],home,BINARY)
    assert record==records[0]
    assert all((home/p).read_bytes()==data for p,data in before.items())
    with pytest.raises(ValueError,match='already exists'): fleet.register_identity(value,spec['name'],home,BINARY)


@pytest.mark.parametrize('method',['broadcast_tx_commit','abci_query','unsafe_flush_mempool'])
def test_remote_client_does_not_allow_privileged_methods(inv,method):
    peer={**inv['nodes'][0],'ports':fleet.ports(inv,inv['nodes'][0]['name'])}
    with pytest.raises(ValueError,match='unapproved'): fleet.remote_call(peer,method)


def test_remote_client_limits_body_disables_proxy_and_redirects(inv,monkeypatch):
    peer={**inv['nodes'][0],'ports':fleet.ports(inv,inv['nodes'][0]['name'])}
    seen=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,size):
            assert size==4*1024*1024+1
            return b'x'*size
    class Opener:
        def open(self,url,timeout):
            assert url.startswith('http://192.168.0.201:') and timeout==2
            return Response()
    def build(*handlers):
        seen.extend(handlers)
        return Opener()
    monkeypatch.setattr(fleet.urllib.request,'build_opener',build)
    with pytest.raises(ValueError,match='size limit'): fleet.remote_call(peer,'block',height=1)
    assert seen[0].proxies=={} and isinstance(seen[1],fleet.NoRedirect)
    with pytest.raises(ValueError,match='redirects'): seen[1].redirect_request(None,None,None,None,None,None)


def test_remote_checkpoint_bootstrap_is_explicit_and_pins_peer_ids(prepared,tmp_path,monkeypatch):
    root,value,_,output,result=prepared
    name='full-b1'; home=tmp_path / 'follower'; shutil.copytree(root / name,home)
    fleet.configure(home,output / name,result['manifest_sha256'][name])
    genesis=fleet.read(home / 'config/genesis.json')
    stamp=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(time.time()-3))
    def call(peer,method,**params):
        if method=='status': return {'node_info':{'network':value['chain_id'],'id':peer['node_id']},'sync_info':{'latest_block_height':'20'}}
        if method=='genesis': return {'genesis':genesis}
        return {'block_id':{'hash':'A'*64},'block':{'header':{'chain_id':value['chain_id'],'height':'17','time':stamp}}}
    monkeypatch.setattr(fleet,'remote_call',call)
    names=['validator-b1','validator-c1']
    path=tmp_path / 'checkpoint.json'
    cp=fleet.fleet_checkpoint(home,path,names)
    assert cp['height']==17
    before=(home / 'config/config.toml').read_bytes()
    expired={**cp,'block_time_ns':time.time_ns()-31*10**9}
    bad=tmp_path / 'expired.json'; fleet.anchors.export(bad,expired)
    with pytest.raises(ValueError,match='expired'): fleet.bootstrap(home,bad,names)
    assert (home / 'config/config.toml').read_bytes()==before
    result=fleet.bootstrap(home,path,names)
    assert result['native_verification_still_required']
    config=tomllib.loads((home / 'config/config.toml').read_text())
    assert config['statesync']['enable'] and config['statesync']['trust_period']=='30s'
    assert '192.168.1.201' in config['statesync']['rpc_servers'] and '192.168.2.201' in config['statesync']['rpc_servers']
    fleet.checked_home(home)


def test_wrong_remote_node_id_cannot_anchor_state_sync(prepared,tmp_path,monkeypatch):
    root,value,_,output,result=prepared
    name='full-b1'; home=tmp_path / 'follower'; shutil.copytree(root / name,home)
    fleet.configure(home,output / name,result['manifest_sha256'][name])
    genesis=fleet.read(home / 'config/genesis.json')
    stamp=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(time.time()-3))
    def call(peer,method,**params):
        if method=='status': return {'node_info':{'network':value['chain_id'],'id':'f'*40},'sync_info':{'latest_block_height':'20'}}
        if method=='genesis': return {'genesis':genesis}
        return {'block_id':{'hash':'A'*64},'block':{'header':{'chain_id':value['chain_id'],'height':'17','time':stamp}}}
    monkeypatch.setattr(fleet,'remote_call',call)
    with pytest.raises(ValueError,match='approved node identity'):
        fleet.fleet_checkpoint(home,tmp_path / 'anchor.json',['validator-b1','validator-c1'])
    assert not (tmp_path / 'anchor.json').exists()
