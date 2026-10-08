"""Fresh follower admission never reassembles the existing genesis or identities."""
import hashlib
import json
from pathlib import Path
import pytest
from computechain.scripts import multisite as fleet
from computechain.scripts import bootstrap_follower as follower
from computechain.scripts import bootstrap_pki as pki
from computechain.scripts import signed_checkpoint as signed


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    binary=fleet.WORKSPACE/'.tools/bin/cometbft'
    if not binary.exists(): pytest.skip('pinned native binary required')
    root=tmp_path/'operator'; root.mkdir()
    monkeypatch.setattr(fleet,'home_root',lambda value:value)  # owned scratch profile only
    inv=fleet.read(fleet.REPO/'deploy/multisite.example.json')
    records=[fleet.init_identity(inv,n['name'],tmp_path/'identities'/n['name'],binary) for n in inv['nodes']]
    bundles=tmp_path/'original'
    fleet.assemble(inv,records,bundles,records[0]['owner'],binary,{n['name']:str(root) for n in inv['nodes']})
    public=signed.key_init(tmp_path/'authority.hex')['public_key']; ca=pki.ca_init(tmp_path/'ca')
    ref=bundles/'validator-a1'; m=fleet.read(ref/'node.json')
    m['network_profile']={'format':1,'chain_id':inv['chain_id'],'endpoints':{
       'validator-a1':{'host':'78.29.35.87','port':27600},'validator-a2':{'host':'78.29.35.87','port':27610},
       'validator-b1':{'host':'178.72.89.199','port':27620},'validator-c1':{'host':'93.171.44.155','port':27630},
       'full-b1':None,'full-c1':None}}
    fleet.write(ref/'node.json',m)
    profile={'format':1,'chain_id':inv['chain_id'],'genesis_sha256':m['genesis_sha256'],
        'ca_sha256':hashlib.sha256(ca.read_bytes()).hexdigest(),'operator_public_key':public,'providers':[]}
    for i,name in enumerate(('validator-b1','validator-c1')):
        node=next(n for n in inv['nodes'] if n['name']==name); record=next(r for r in records if r['name']==name)
        profile['providers'].append({'name':name,'node_id':record['node_id'],'location':node['location'],
            'url':'https://'+m['network_profile']['endpoints'][name]['host']+':'+str(27626+i*10),'certificate_sha256':str(i+1)*64})
    profile_file=tmp_path/'profile.json'; fleet.write(profile_file,profile)
    inventory_file=tmp_path/'inventory.json'; fleet.write(inventory_file,inv)
    return root,inventory_file,ref,profile_file,fleet.digest_file(profile_file),ca,binary


def test_new_follower_preserves_genesis_and_original_keys(prepared,tmp_path):
    root,inventory,ref,profile,sha,ca,binary=prepared
    before={str(p):p.read_bytes() for p in ref.rglob('*') if p.is_file()}
    result=follower.create(root,inventory,ref,'full-aa3',profile,sha,ca,tmp_path/'admission',binary)
    home=Path(result['home']); manifest=fleet.checked_home(home)
    assert result['genesis_unchanged'] and not result['added_validator'] and not result['private_keys_exported']
    assert manifest['node']['role']=='full' and manifest['node']['stake_cpc']==0
    assert (home/'config/genesis.json').read_bytes()==(ref/'genesis.json').read_bytes()
    assert all(Path(p).read_bytes()==raw for p,raw in before.items())
    assert manifest['registration']['node_id']!=fleet.read(ref/'node.json')['registration']['node_id']
    assert (home/'owner-private.hex').stat().st_mode&0o777==0o600
    config=fleet.tomllib.loads((home/'config/config.toml').read_text())
    assert not config['statesync']['enable'] and not config['p2p']['pex']
    assert len(config['p2p']['persistent_peers'].split(','))==2 and '@192.168.' not in config['p2p']['persistent_peers']
    with pytest.raises(ValueError,match='NEW'):
        follower.create(root,inventory,ref,'full-aa3',profile,sha,ca,tmp_path/'other-admission',binary)


def test_wrong_profile_sha_is_refused_before_generating_keys(prepared,tmp_path):
    root,inventory,ref,profile,_,ca,binary=prepared
    with pytest.raises(ValueError,match='manifest SHA'):
        follower.create(root,inventory,ref,'full-aa3',profile,'f'*64,ca,tmp_path/'admission',binary)
    assert not (root/fleet.read(inventory)['chain_id']/'nodes/full-aa3').exists()
