"""Checkpoint policy and preflight isolation: fake RPC, no host processes/keys."""
from copy import deepcopy
import hashlib
import json
import os
import time

import pytest

from computechain.scripts import comet_checkpoint as anchors
from computechain.scripts import comet_devnet as devnet

NOW = 1_800_000_000 * 10**9
STAMP = NOW - 3 * 10**9
HASH = "A" * 64


@pytest.fixture
def network(tmp_path):
    genesis = {"chain_id":"checkpoint-test","app_state":{"schema":3}}
    raw = json.dumps(genesis).encode()
    nodes = []
    for i in range(6):
        node = tmp_path / f"node{i}"
        (node / "config").mkdir(parents=True)
        (node / "data").mkdir()
        (node / "config/genesis.json").write_bytes(raw)
        (node / "config/config.toml").write_text('log_level = "error"\n[statesync]\nenable = false\n')
        (node / "data/priv_validator_state.json").write_text('{"height":"0"}')
        nodes.append(str(node))
    config = {"schema":3,"chain_id":"checkpoint-test","genesis_sha256":hashlib.sha256(raw).hexdigest(),
        "nodes":nodes,"base_port":28600}
    devnet.write(tmp_path / "network.json",config)
    devnet.write(tmp_path / "processes.json",{})
    cp = {"format":1,"app_version":3,"chain_id":config["chain_id"],"genesis_sha256":config["genesis_sha256"],
        "height":17,"block_hash":HASH,"block_time_ns":STAMP,"trust_period_seconds":30}
    replies = {}
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(STAMP//10**9))
    for i in range(3):
        replies[i] = {
            "status":{"node_info":{"network":config["chain_id"],"id":f"{i+1:040x}"},"sync_info":{"latest_block_height":"20"}},
            "genesis":{"genesis":genesis},
            "block":{"block_id":{"hash":HASH},"block":{"header":{"chain_id":config["chain_id"],"height":"17","time":stamp}}}}
    def call(i,method,**params):
        assert params["timeout"] == 2
        return deepcopy(replies[i][method])
    return tmp_path, config, cp, replies, call


def test_capture_and_atomic_export_roundtrip(network):
    root, config, cp, replies, call = network
    assert anchors.capture(config,call,now_ns=NOW) == cp
    path = root / "anchor.json"
    anchors.export(path,cp)
    assert anchors.load(path) == cp
    with pytest.raises(FileExistsError):
        anchors.export(path,{**cp,"block_hash":"B"*64})
    assert anchors.load(path) == cp
    assert not list(root.glob('.checkpoint-*'))


@pytest.mark.parametrize("change",[
    {"chain_id":"wrong"},{"genesis_sha256":"f"*64},{"app_version":2},{"format":2},
    {"height":True},{"height":0},{"height":2**63},{"block_hash":"a"*64},
    {"block_time_ns":NOW+1},{"block_time_ns":NOW-30*10**9},{"trust_period_seconds":60},
    {"extra":"unexpected"}])
def test_wrong_or_expired_anchor_is_rejected(network,change):
    _, config, cp, _, _ = network
    with pytest.raises(ValueError):
        anchors.validate({**cp,**change},config,now_ns=NOW)


def test_nanosecond_time_and_strict_expiration(network):
    _,config,cp,_,_=network
    assert anchors.block_time_ns('2026-10-07T00:00:00.123456789Z') % 10**9 == 123456789
    assert anchors.validate({**cp,"block_time_ns":NOW-30*10**9+1},config,now_ns=NOW)>0
    with pytest.raises(ValueError,match="expired"):
        anchors.validate({**cp,"block_time_ns":NOW-30*10**9},config,now_ns=NOW)


def test_missing_witness_can_fail_over_but_one_is_not_enough(network):
    _,config,cp,replies,call=network
    def missing(i,method,**params):
        if i == 1:
            raise OSError('offline')
        return call(i,method,**params)
    result=anchors.check_witnesses(cp,config,missing,(0,1,2),now_ns=NOW)
    assert result["witnesses"]==[0,2] and result["unavailable"]==[{"node":1,"reason":"OSError"}]
    with pytest.raises(ValueError,match="fewer than two"):
        anchors.check_witnesses(cp,config,missing,(0,1),now_ns=NOW)
    assert anchors.capture(config,missing,(1,0,2),now_ns=NOW)==cp


@pytest.mark.parametrize("fault",["hash","time","genesis","chain","node_id","height"])
def test_any_contradictory_witness_fails_closed(network,fault):
    _,config,cp,replies,call=network
    if fault=="hash": replies[1]["block"]["block_id"]["hash"]="B"*64
    if fault=="time": replies[1]["block"]["block"]["header"]["time"]='2026-10-07T00:00:00Z'
    if fault=="genesis": replies[1]["genesis"]["genesis"]={"chain_id":config["chain_id"],"app_state":{"schema":2}}
    if fault=="chain": replies[1]["status"]["node_info"]["network"]="other"
    if fault=="node_id": replies[1]["status"]["node_info"]["id"]=replies[0]["status"]["node_info"]["id"]
    if fault=="height": replies[1]["status"]["sync_info"]["latest_block_height"]="16"
    with pytest.raises(ValueError):
        anchors.check_witnesses(cp,config,call,(0,1,2),now_ns=NOW)


def test_startup_budget_and_local_genesis_pin(network):
    root,config,cp,_,call=network
    with pytest.raises(ValueError,match="near expiry"):
        anchors.check_witnesses(cp,config,call,(0,1),now_ns=STAMP+21*10**9)
    (root / "node0/config/genesis.json").write_text('{}')
    with pytest.raises(ValueError,match="pinned"):
        anchors.check_witnesses(cp,config,call,(0,1),now_ns=NOW)


@pytest.mark.parametrize("remote_stamp", [
    "2026-10-08T05:03:41.98268Z", "2026-10-08T05:03:41.982680000Z"])
def test_native_genesis_timestamp_reserialization_preserves_identity(network, remote_stamp):
    root, config, cp, replies, call = network
    local = deepcopy(replies[0]["genesis"]["genesis"])
    local["genesis_time"] = "2026-10-08T05:03:41.982680Z"
    raw = json.dumps(local).encode()
    (root / "node0/config/genesis.json").write_bytes(raw)
    config["genesis_sha256"] = cp["genesis_sha256"] = hashlib.sha256(raw).hexdigest()
    for reply in replies.values():
        reply["genesis"]["genesis"] = {**local, "genesis_time": remote_stamp}
    assert anchors.check_witnesses(cp, config, call, (0, 1), now_ns=NOW)["witnesses"] == [0, 1]
    assert (root / "node0/config/genesis.json").read_bytes() == raw


@pytest.mark.parametrize("change", [
    {"genesis_time": "2026-10-08T05:03:41.982680001Z"},
    {"genesis_time": "2026-10-08T05:03:41.98268+00:00"},
    {"genesis_time": 1791435821982680000},
    {"app_hash": "A" * 64}, {"app_state": {"schema": 2}},
])
def test_genesis_time_normalization_does_not_accept_other_changes(network, change):
    root, config, cp, replies, call = network
    local = deepcopy(replies[0]["genesis"]["genesis"])
    local["genesis_time"] = "2026-10-08T05:03:41.982680Z"
    raw = json.dumps(local).encode()
    (root / "node0/config/genesis.json").write_bytes(raw)
    config["genesis_sha256"] = cp["genesis_sha256"] = hashlib.sha256(raw).hexdigest()
    for reply in replies.values():
        reply["genesis"]["genesis"] = deepcopy(local)
    replies[1]["genesis"]["genesis"].update(change)
    with pytest.raises(ValueError):
        anchors.check_witnesses(cp, config, call, (0, 1), now_ns=NOW)


def test_bounded_file_duplicate_fields_and_existing_symlink(network):
    root,_,cp,_,_=network
    path=root / "bad.json"
    path.write_bytes(b'x'*(anchors.MAX_FILE_BYTES+1))
    with pytest.raises(ValueError,match="too large"): anchors.load(path)
    path.write_text('{"height":1,"height":2}')
    with pytest.raises(ValueError,match="duplicate"): anchors.load(path)
    link=root / "link.json"
    link.symlink_to(path)
    with pytest.raises(FileExistsError): anchors.export(link,cp)
    assert path.read_text()=='{"height":1,"height":2}'


@pytest.mark.parametrize("indexes",[(0,),(0,0),(0,9),(0,True)])
def test_witness_index_bounds(network,indexes):
    _,config,_,_,_=network
    with pytest.raises(ValueError): anchors.witnesses(config,indexes)


@pytest.mark.parametrize("fault",["expired","target_genesis","signed","application","native","symlink","config_symlink","self_witness"])
def test_preflight_failure_changes_no_config_processes_or_data(network,monkeypatch,fault):
    root,config,cp,_,call=network
    node=root / "node5"
    if fault=="expired": cp["block_time_ns"]=NOW-30*10**9
    if fault=="target_genesis": (node / "config/genesis.json").write_text('{}')
    if fault=="signed": (node / "data/priv_validator_state.json").write_text('{"height":"1"}')
    if fault=="application":
        (node / "application").mkdir()
        (node / "application/application.sqlite").write_bytes(b'preserve-database')
    if fault=="native": (node / "data/state.db").mkdir()
    if fault=="symlink": (node / "application").symlink_to(root / "node4")
    if fault=="config_symlink":
        (node / 'config/config.toml').unlink()
        (node / 'config/config.toml').symlink_to(root / 'node4/config/config.toml')
    path=root / "anchor.json"
    anchors.export(path,cp)
    before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
    monkeypatch.setattr(anchors.time,"time_ns",lambda:NOW)
    monkeypatch.setattr(devnet,"rpc",lambda conf,i,method,**params:call(i,method,**params))
    net=devnet.Network(root)
    monkeypatch.setattr(net,"start_node",lambda i:pytest.fail('preflight must precede process start'))
    with pytest.raises(ValueError): net.state_sync(5,path,witnesses=(0,5) if fault=="self_witness" else (0,1))
    assert {p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}==before


@pytest.mark.parametrize('command',['checkpoint','state-sync'])
def test_operator_launcher_forwards_explicit_anchor_and_witnesses(network,monkeypatch,command):
    import argparse
    from types import SimpleNamespace
    from computechain.scripts import devnet as launcher
    root,_,_,_,_=network
    calls=[]
    class FakeNetwork:
        def __init__(self,path): assert path==root
        def checkpoint(self,path,witnesses):
            calls.append((path,witnesses))
            return {'ok':True}
        def state_sync(self,i,path,witnesses):
            calls.append((i,path,witnesses))
            return {'ok':True}
    monkeypatch.setattr(launcher,'Network',FakeNetwork)
    args=SimpleNamespace(command=command,checkpoint=root / 'anchor.json',witnesses=[0,1,2],node=5)
    launcher.execute(root,args,argparse.ArgumentParser())
    expected=(args.checkpoint,[0,1,2]) if command=='checkpoint' else (5,args.checkpoint,[0,1,2])
    assert calls==[expected]
    args.checkpoint=None
    with pytest.raises(SystemExit): launcher.execute(root,args,argparse.ArgumentParser())


def test_config_io_failure_preserves_previous_file(network,monkeypatch):
    root,_,_,_,_=network
    path=root / 'node5/config/config.toml'
    before=path.read_bytes()
    def fail(*args): raise OSError('injected config I/O error')
    monkeypatch.setattr(devnet.os,'replace',fail)
    with pytest.raises(OSError,match='I/O'):
        devnet.set_toml(path,'statesync',{'enable':'true'})
    assert path.read_bytes()==before
    assert not list(path.parent.glob('.config-*'))


def test_atomic_config_replacement_preserves_service_owner_and_mode(tmp_path):
    path=tmp_path/'config.toml'
    path.write_text('[statesync]\nenable=false\n')
    path.chmod(0o600)
    if os.geteuid()==0:
        os.chown(path,65534,65534)
    before=path.stat()
    devnet.set_toml(path,'statesync',{'enable':'true'})
    after=path.stat()
    assert (after.st_uid,after.st_gid,after.st_mode&0o777)==(before.st_uid,before.st_gid,0o600)
    assert 'enable = true' in path.read_text()
