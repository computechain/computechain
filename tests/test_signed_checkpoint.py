from copy import deepcopy
import time
import pytest
from computechain.scripts import signed_checkpoint as signed


@pytest.fixture
def attestation(tmp_path):
    key=tmp_path/'operator.hex'; public=signed.key_init(key)['public_key']
    now=time.time_ns()
    config={'schema':3,'chain_id':'test-chain','genesis_sha256':'a'*64}
    checkpoint={'format':1,'app_version':3,'chain_id':'test-chain','genesis_sha256':'a'*64,
                'height':100,'block_hash':'B'*64,'block_time_ns':now-5*10**9,'trust_period_seconds':30}
    envelope=signed.sign(key,checkpoint,config)
    return key,public,config,checkpoint,envelope,now


def test_operator_signed_checkpoint_and_no_overwrite(attestation,tmp_path):
    key,public,config,checkpoint,envelope,now=attestation
    assert signed.verify(envelope,public,config,now)==checkpoint
    path=tmp_path/'signed.json'; signed.export(path,envelope)
    assert signed.verify(signed.load(path),public,config,now)==checkpoint
    with pytest.raises(FileExistsError): signed.export(path,envelope)
    with pytest.raises(ValueError,match='already exists'): signed.key_init(key)
    assert key.stat().st_mode&0o777==0o600


@pytest.mark.parametrize('fault',['authority','signature','height','genesis','expiry','future','domain','extra'])
def test_bad_operator_checkpoint_fails_closed(attestation,fault):
    key,public,config,checkpoint,envelope,now=attestation
    value=deepcopy(envelope)
    if fault=='authority': value['authority']='c'*64
    if fault=='signature': value['signature']='0'*128
    if fault=='height': value['checkpoint']['height']+=1
    if fault=='genesis': config={**config,'genesis_sha256':'c'*64}
    if fault=='expiry': now+=31*10**9
    if fault=='future': now-=10*10**9
    if fault=='domain':
        signer=signed.SigningKey.from_string(bytes.fromhex(key.read_text()),curve=signed.Ed25519)
        value['signature']=signer.sign(signed.canonical(checkpoint)).hex()
    if fault=='extra': value['expiry_override']=True
    with pytest.raises(ValueError): signed.verify(value,public,config,now)
