"""Network-only migration uses owned scratch homes and mocked kernel/systemd."""
from copy import deepcopy
import os
from pathlib import Path
import shutil
import pytest
from computechain.scripts import multisite as fleet
from computechain.scripts import fleet_network as wan

BINARY=fleet.WORKSPACE/'.tools/bin/cometbft'


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    if not BINARY.exists(): pytest.skip('pinned Comet binary required')
    root=tmp_path_factory.mktemp('wan-profile')
    value=fleet.read(fleet.REPO/'deploy/multisite.example.json')
    records=[fleet.init_identity(value,n['name'],root/n['name'],BINARY) for n in value['nodes']]
    output=root/'original'; result=fleet.assemble(value,records,output,records[0]['owner'],BINARY)
    profile={'format':1,'chain_id':value['chain_id'],'endpoints':{
        'validator-a1':{'host':'78.29.35.87','port':27600},'validator-a2':{'host':'78.29.35.87','port':27610},
        'validator-b1':{'host':'178.72.89.199','port':27620},'validator-c1':{'host':'93.171.44.155','port':27630},
        'full-b1':None,'full-c1':None}}
    update=root/'updated'; approvals=wan.plan(output,profile,update)
    return root,value,profile,output,update,result,approvals


def test_network_bundle_changes_only_p2p_firewall_and_manifest(prepared):
    _,value,profile,original,updated,_,_=prepared
    for node in value['nodes']:
        old=fleet.read(original/node['name']/'node.json'); new=fleet.read(updated/node['name']/'node.json')
        assert new['network_profile']==profile
        assert new['registration']==old['registration'] and new['genesis_sha256']==old['genesis_sha256']
        assert {f for f in old['files'] if old['files'][f]!=new['files'][f]}=={'config.toml','firewall.nft'}
        old_cfg=fleet.tomllib.loads((original/node['name']/'config.toml').read_text())
        new_cfg=fleet.tomllib.loads((updated/node['name']/'config.toml').read_text())
        assert all(old_cfg[k]==new_cfg[k] for k in old_cfg if k!='p2p')
        assert not new_cfg['p2p']['pex'] and not new_cfg['statesync']['enable']
        assert new_cfg['rpc']['laddr'].startswith('tcp://127.0.0.1:')
        assert '@192.168.' not in new_cfg['p2p']['persistent_peers']
        before=(original/node['name']/'firewall.nft').read_text(); after=(updated/node['name']/'firewall.nft').read_text()
        assert before.split('set readers',1)[1]==after.split('set readers',1)[1]
        assert '31.77.195.224' not in after and '178.72.89.199' in after


@pytest.mark.parametrize('fault',['private','multicast','dns','bool-port','duplicate','missing-validator','unknown-node','shared-exit','wrong-chain'])
def test_bad_wan_profile_rejected_before_output(prepared,tmp_path,fault):
    _,_,profile,original,_,_,_=prepared
    value=deepcopy(profile)
    if fault=='private': value['endpoints']['validator-b1']['host']='192.168.1.205'
    if fault=='multicast': value['endpoints']['validator-b1']['host']='224.0.0.1'
    if fault=='dns': value['endpoints']['validator-b1']['host']='example.com'
    if fault=='bool-port': value['endpoints']['validator-b1']['port']=True
    if fault=='duplicate': value['endpoints']['validator-a2']=deepcopy(value['endpoints']['validator-a1'])
    if fault=='missing-validator': value['endpoints']['validator-b1']=None
    if fault=='unknown-node': value['endpoints']['extra-node']=None
    if fault=='shared-exit': value['endpoints']['validator-b1']['host']='78.29.35.87'
    if fault=='wrong-chain': value['chain_id']='foreign-chain'
    output=tmp_path/'unsafe'
    with pytest.raises(ValueError): wan.plan(original,value,output)
    assert not output.exists()


def test_same_host_peers_stay_local_and_unpublished_remote_fulls_are_not_dialed(prepared):
    _,_,profile,original,_,_,_=prepared
    m=fleet.read(original/'validator-a1/node.json')
    m['peers'][0]['host']=m['node']['host']; m['network_profile']=profile
    peers=wan.peer_addresses(m)
    assert peers[0][1:]==(m['node']['host'],m['peers'][0]['ports']['p2p'])
    assert all(p['role']=='validator' for p,_,_ in peers)


@pytest.fixture
def installed(prepared,tmp_path,monkeypatch):
    if os.geteuid()!=0: pytest.skip('root-owned configuration guard integration requires root')
    root,value,profile,original,_,_,_=prepared
    name=value['nodes'][0]['name']; home=tmp_path/value['chain_id']/'nodes'/name
    home.parent.mkdir(parents=True); shutil.copytree(root/name,home)
    old=fleet.read(original/name/'node.json')
    old['home_root']=str(tmp_path); old['application_home']=str(tmp_path/value['chain_id']/'apps'/name)
    for filename in old['files']:
        target=home/'config'/filename if filename in ('config.toml','genesis.json') else home/filename
        shutil.copyfile(original/name/filename,target)
    fleet.write(home/'node.json',old); old_sha=fleet.digest_file(home/'node.json')
    bundle=tmp_path/'new-bundle'; bundle.mkdir()
    new,config,firewall=wan.render(old,wan.bounded(home/'config/config.toml'),wan.bounded(home/'firewall.nft'),profile,old_sha)
    for filename in old['files']:
        raw=config if filename=='config.toml' else firewall if filename=='firewall.nft' else wan.bounded(original/name/filename)
        (bundle/filename).write_bytes(raw)
    fleet.write(bundle/'node.json',new)
    ops_root=tmp_path/'private-etc/computechain'; ops=ops_root/value['chain_id']/name
    ops.mkdir(parents=True); shutil.copyfile(home/'firewall.nft',ops/'firewall.nft')
    monkeypatch.setattr(wan,'OPS_ROOT',ops_root); monkeypatch.setattr(wan,'safe_root',lambda _:tmp_path)
    monkeypatch.setattr(wan,'stopped',lambda _:None)
    transactions=[]
    monkeypatch.setattr(wan,'nft_command',lambda m,text,check=False:transactions.append((text,check)))
    return home,bundle,old_sha,fleet.digest_file(bundle/'node.json'),transactions,ops/'firewall.nft'


def test_apply_preserves_identity_signer_and_existing_history(installed):
    home,bundle,old,new,transactions,ops=installed
    history=home/'data/blockstore.db'; history.mkdir(); (history/'owned-history').write_bytes(b'keep history')
    state=fleet.read(home/'data/priv_validator_state.json'); state['height']='999'
    fleet.write(home/'data/priv_validator_state.json',state)
    private={str(p.relative_to(home)):p.read_bytes() for p in (home/'owner-private.hex',home/'config/node_key.json',home/'config/priv_validator_key.json',home/'data/priv_validator_state.json')}
    marker_stat=(home/'node.json').stat(); result=wan.apply(home,bundle,old,new)
    assert result['keys_and_signing_state_preserved'] and result['genesis_unchanged']
    assert fleet.digest_file(home/'node.json')==new and fleet.checked_home(home)['network_profile']
    assert all((home/p).read_bytes()==raw for p,raw in private.items())
    assert (history/'owned-history').read_bytes()==b'keep history'
    assert (home/'node.json').stat().st_uid==marker_stat.st_uid
    assert [check for _,check in transactions]==[True,False]
    assert ops.read_bytes()==(bundle/'firewall.nft').read_bytes()


def test_live_node_is_refused_without_mutation(installed,monkeypatch):
    home,bundle,old,new,transactions,_=installed
    monkeypatch.setattr(wan,'stopped',lambda _: (_ for _ in ()).throw(ValueError('stop node')))
    with pytest.raises(ValueError,match='stop node'): wan.apply(home,bundle,old,new)
    assert fleet.digest_file(home/'node.json')==old and not transactions


def test_immutable_manifest_change_is_refused(installed):
    home,bundle,old,_,transactions,_=installed
    altered=fleet.read(bundle/'node.json'); altered['registration']['owner']='foreign-owner'
    fleet.write(bundle/'node.json',altered)
    with pytest.raises(ValueError,match='immutable'): wan.apply(home,bundle,old,fleet.digest_file(bundle/'node.json'))
    assert fleet.digest_file(home/'node.json')==old and not transactions


def test_files_and_scoped_acl_rollback_on_atomic_failure(installed,monkeypatch):
    home,bundle,old,new,transactions,ops=installed
    before={home/'config/config.toml':wan.bounded(home/'config/config.toml'),ops:wan.bounded(ops)}
    original=wan.atomic_public; failed=False
    def write(path,raw):
        nonlocal failed
        if path==ops and not failed:
            failed=True; raise OSError('injected atomic write failure')
        return original(path,raw)
    monkeypatch.setattr(wan,'atomic_public',write)
    with pytest.raises(OSError,match='injected'): wan.apply(home,bundle,old,new)
    assert all(path.read_bytes()==raw for path,raw in before.items())
    assert fleet.digest_file(home/'node.json')==old and fleet.checked_home(home)
    assert len(transactions)==2 and transactions[-1][0]==wan.bounded(home/'firewall.nft').decode()
