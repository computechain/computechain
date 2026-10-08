from copy import deepcopy
import hashlib
import ssl
import pytest
from computechain.scripts import bootstrap_protocol as protocol
from computechain.scripts import bootstrap_pki as pki
from computechain.scripts import signed_checkpoint as signed


@pytest.fixture
def profile(tmp_path):
    ca=pki.ca_init(tmp_path/'ca')
    public=signed.key_init(tmp_path/'operator.hex')['public_key']
    config={'schema':3,'chain_id':'test-chain','genesis_sha256':'a'*64}
    value={'format':1,'chain_id':'test-chain','genesis_sha256':'a'*64,'ca_sha256':hashlib.sha256(ca.read_bytes()).hexdigest(),
           'operator_public_key':public,'providers':[
               {'name':'provider-aa','location':'site-aa','node_id':'a'*40,'url':'https://178.72.89.199:27626','certificate_sha256':'b'*64},
               {'name':'provider-bb','location':'site-bb','node_id':'b'*40,'url':'https://93.171.44.155:27636','certificate_sha256':'c'*64}]}
    return value,config,ca


def test_profile_requires_explicit_independent_https_identities(profile):
    value,config,ca=profile
    assert protocol.profile(value,config)==value
    context=protocol.trust_context(ca,value['ca_sha256'])
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    assert context.minimum_version==ssl.TLSVersion.TLSv1_3


@pytest.mark.parametrize('fault',['http','dns','private','credentials','redirect-path','bool-format','wrong-genesis','same-site','same-host','same-cert','same-id','weak-operator'])
def test_unsafe_provider_trust_is_rejected(profile,fault):
    value,config,ca=profile; value=deepcopy(value)
    a,b=value['providers']
    if fault=='http': a['url']='http://178.72.89.199:27626'
    if fault=='dns': a['url']='https://example.com:27626'
    if fault=='private': a['url']='https://192.168.1.205:27626'
    if fault=='credentials': a['url']='https://admin:password@178.72.89.199:27626'
    if fault=='redirect-path': a['url']='https://178.72.89.199:27626/elsewhere'
    if fault=='bool-format': value['format']=True
    if fault=='wrong-genesis': value['genesis_sha256']='d'*64
    if fault=='same-site': b['location']=a['location']
    if fault=='same-host': b['url']='https://178.72.89.199:27636'
    if fault=='same-cert': b['certificate_sha256']=a['certificate_sha256']
    if fault=='same-id': b['node_id']=a['node_id']
    if fault=='weak-operator': value['operator_public_key']='0'*64
    with pytest.raises(ValueError): protocol.profile(value,config)


def test_ca_corruption_or_symlink_not_accepted(profile,tmp_path):
    value,_,ca=profile
    with pytest.raises(ValueError,match='CA differs'): protocol.trust_context(ca,'f'*64)
    link=tmp_path/'ca-link'; link.symlink_to(ca)
    with pytest.raises(ValueError,match='symlink'): protocol.trust_context(link,value['ca_sha256'])


def test_doctor_will_not_use_empty_db_as_expired_anchor_bypass(profile,tmp_path,monkeypatch):
    import time
    from computechain.scripts import multisite as fleet
    value,config,_=profile
    (tmp_path/'config').mkdir(); (tmp_path/'config/config.toml').write_text('[statesync]\nenable=true\n')
    (tmp_path/'data/blockstore.db').mkdir(parents=True)  # partial native bootstrap, NOT committed history
    key=tmp_path/'authority.hex'; public=signed.key_init(key)['public_key']; value['operator_public_key']=public
    anchor={'format':1,'app_version':3,'chain_id':config['chain_id'],'genesis_sha256':config['genesis_sha256'],
        'height':100,'block_hash':'B'*64,'block_time_ns':time.time_ns()-5*10**9,'trust_period_seconds':30}
    envelope=signed.sign(key,anchor,config)
    manifest={'schema':3,'chain_id':config['chain_id'],'genesis_sha256':config['genesis_sha256'],'binary_sha256':'c'*64,
        'node':{'name':'full-qa','host':'192.168.0.100'},'peers':[],'bootstrap_profile':value,
        'state_sync_anchor':anchor,'checkpoint_attestation':envelope}
    monkeypatch.setattr(fleet,'read',lambda _:manifest)
    monkeypatch.setattr(fleet,'checked_home',lambda _:manifest)
    monkeypatch.setattr(fleet,'binary_identity',lambda _:'c'*64)
    monkeypatch.setattr(fleet,'digest_file',lambda _:config['genesis_sha256'])
    monkeypatch.setattr(protocol,'pinned_trust',lambda *args:value)
    def command(args,**kwargs):
        return 'yes\n' if args[0]=='timedatectl' else '[{"addr_info":[{"local":"192.168.0.100"}]}]'
    monkeypatch.setattr(fleet.subprocess,'check_output',command)
    # Signature authenticity still passes; actual time expiry must fail even with
    # a blockstore directory created by a failed first launch.
    monkeypatch.setattr(signed.anchors.time,'time_ns',lambda:anchor['block_time_ns']+31*10**9)
    with pytest.raises(ValueError,match='expired'): fleet.doctor(tmp_path,tmp_path/'binary')


def test_staged_signed_follower_never_silently_falls_back_to_full_sync(profile,tmp_path,monkeypatch):
    from computechain.scripts import multisite as fleet
    value,config,_=profile
    (tmp_path/'config').mkdir(); (tmp_path/'config/config.toml').write_text('[statesync]\nenable=false\n')
    m={'schema':3,'chain_id':config['chain_id'],'genesis_sha256':config['genesis_sha256'],'binary_sha256':'c'*64,
       'node':{'name':'full-qa','host':'192.168.0.100'},'peers':[],'bootstrap_profile':value}
    monkeypatch.setattr(fleet,'read',lambda _:m); monkeypatch.setattr(fleet,'checked_home',lambda _:m)
    monkeypatch.setattr(fleet,'binary_identity',lambda _:'c'*64); monkeypatch.setattr(fleet,'digest_file',lambda _:config['genesis_sha256'])
    monkeypatch.setattr(protocol,'pinned_trust',lambda *args:value)
    monkeypatch.setattr(fleet.subprocess,'check_output',lambda args,**k:'yes\n' if args[0]=='timedatectl' else '[{"addr_info":[{"local":"192.168.0.100"}]}]')
    with pytest.raises(ValueError,match='awaits checkpoint'): fleet.doctor(tmp_path,tmp_path/'binary')


@pytest.fixture
def empty_retry(tmp_path,monkeypatch):
    import json
    import os
    from computechain.blockchain.comet.storage import Store
    from computechain.scripts import fleet_network
    home=tmp_path/'node'; (home/'data').mkdir(parents=True)
    (home/'data/priv_validator_state.json').write_text(json.dumps({'height':'0'}))
    app=tmp_path/'app'
    store=Store(app,'test-chain'); store.close()
    manifest={'node':{'role':'full'},'application_home':str(app),'checkpoint_attestation':{}}
    monkeypatch.setattr(os,'geteuid',lambda:0)
    monkeypatch.setattr(protocol,'pinned_trust',lambda *args:{'operator_public_key':'a'*64})
    monkeypatch.setattr(signed,'verify_signature',lambda *args:None)
    monkeypatch.setattr(fleet_network,'stopped',lambda *args:None)
    return home,app,manifest


def test_explicit_empty_retry_preserves_application_database(empty_retry):
    home,app,manifest=empty_retry
    before={p.name:p.read_bytes() for p in app.iterdir()}
    result=protocol.uninitialized_application(home,manifest)
    assert result['database_preserved'] and result['committed']==0
    assert all((app/name).read_bytes()==raw for name,raw in before.items())
    # SQLite read-only WAL readers may create empty WAL/shared-memory sidecars;
    # the actual database and pre-existing bytes must never be replaced.
    assert {p.name for p in app.iterdir()}-set(before)<= {'application.sqlite-wal','application.sqlite-shm'}


@pytest.mark.parametrize('fault',['committed','receipts','snapshots','native','signed','staging','symlink','completed','active','writer','authority'])
def test_empty_retry_refuses_history_or_unproven_stopped_follower(empty_retry,monkeypatch,fault):
    import fcntl
    import sqlite3
    from computechain.scripts import fleet_network
    home,app,manifest=empty_retry
    writer=None
    if fault in ('committed','receipts','snapshots'):
        connection=sqlite3.connect(app/'application.sqlite')
        values={'committed':(1,b'{}',b'x'),'receipts':('x',1,b'{}'),'snapshots':(1,b'x',b'{}')}[fault]
        connection.execute('INSERT INTO '+fault+' VALUES (?,?,?)',values); connection.commit(); connection.close()
    if fault=='native': (home/'data/blockstore.db').mkdir()
    if fault=='signed': (home/'data/priv_validator_state.json').write_text('{"height":"1"}')
    if fault=='staging': (app/'restore-staging.sqlite').write_bytes(b'preserve')
    if fault=='symlink': (app/'unapproved-link').symlink_to(app/'application.sqlite')
    if fault=='completed': manifest['bootstrap_completed']={}
    if fault=='active': monkeypatch.setattr(fleet_network,'stopped',lambda *a:(_ for _ in ()).throw(ValueError('active')))
    if fault=='authority': monkeypatch.setattr(signed,'verify_signature',lambda *a:(_ for _ in ()).throw(ValueError('authority')))
    if fault=='writer':
        writer=(app/'.writer.lock').open('rb'); fcntl.flock(writer,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before=(app/'application.sqlite').read_bytes()
    try:
        with pytest.raises((ValueError,OSError)):
            protocol.uninitialized_application(home,manifest)
        assert (app/'application.sqlite').read_bytes()==before
    finally:
        if writer: writer.close()
