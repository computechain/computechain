"""LAN gateway guards use scratch configs, never start/stop real Docker services."""
import json
import pytest
from computechain.scripts import web_services as web


@pytest.mark.parametrize("host",["0.0.0.0","8.8.8.8","localhost","192.0.2.1","::"])
def test_private_bind_only(host):
    with pytest.raises(ValueError):
        web.private_host(host)


def test_web_settings_follow_network_ports_and_saved_lan(tmp_path):
    (tmp_path/"network.json").write_text(json.dumps({"base_port":29600}))
    config=web.settings(tmp_path,"explorer","192.168.0.100",4100)
    assert config=={"host":"192.168.0.100","port":4100,"api_port":29800,"frontend_port":29801}
    folder=tmp_path/"explorer"
    folder.mkdir()
    web.save(folder/"settings.json",config)
    assert web.settings(tmp_path,"explorer")==config


@pytest.mark.parametrize("service",["website","explorer"])
def test_gateway_is_read_only_and_does_not_proxy_comet(service):
    config={"host":"192.168.0.100","port":4000,"api_port":28800,"frontend_port":28801}
    text=web.nginx(config,service)
    assert "listen 192.168.0.100:4000;" in text
    assert "^(GET|HEAD)$" in text and "return 405;" in text
    assert "127.0.0.1:28601" not in text and "broadcast_tx" not in text
    if service=="website":
        assert "location = /api/stats" in text and "location /api/ { return 404; }" in text


def test_unconfigured_stop_is_noop(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(web,"compose",lambda *a: calls.append(a))
    web.control(tmp_path,"website","down")
    assert calls==[]


def test_only_configured_edge_can_forward_https(tmp_path):
    config=web.settings(tmp_path,"explorer","192.168.0.100",4000,"192.168.0.13")
    assert config["trusted_proxy"] == "192.168.0.13"
    text=web.nginx(config,"explorer")
    assert '"192.168.0.13:https" https;' in text
    assert 'default $scheme;' in text
    assert 'proxy_set_header X-Forwarded-Proto $web_scheme;' in text
    assert 'proxy_set_header Host $http_host;' in text  # preserve LAN port in redirects
    directory=tmp_path/"explorer"
    directory.mkdir()
    web.save(directory/"settings.json",config)
    assert web.settings(tmp_path,"explorer")==config
    with pytest.raises(ValueError):
        web.settings(tmp_path,"explorer",trusted_proxy="0.0.0.0")


@pytest.fixture
def pinned_observer(tmp_path,monkeypatch):
    import hashlib
    from computechain.scripts import multisite as fleet, rpc_read_gateway as reads
    (tmp_path/'network.json').write_text(json.dumps({'base_port':28600,'chain_id':'old-chain'}))
    old=tmp_path/'explorer/index'; old.mkdir(parents=True)
    (old/'index.sqlite').write_bytes(b'preserve-old-history')
    home=tmp_path/'full-node'; (home/'config').mkdir(parents=True)
    raw=json.dumps({'chain_id':'new-chain','app_state':{'schema':3}}).encode()
    (home/'config/genesis.json').write_bytes(raw)
    manifest={'chain_id':'new-chain','node':{'role':'full'},'genesis_sha256':hashlib.sha256(raw).hexdigest(),
              'registration':{'node_id':'a'*40},'ports':{'rpc':27641}}
    status={'node_info':{'id':'a'*40,'network':'new-chain'},
            'sync_info':{'catching_up':False,'earliest_block_height':'1'}}
    monkeypatch.setattr(fleet,'checked_home',lambda _:manifest)
    monkeypatch.setattr(reads,'read_native',lambda *args:{'result':status})
    return tmp_path,home,status


def test_observer_switch_preserves_old_index_and_persists_new_source(pinned_observer):
    root,home,_=pinned_observer
    source=web.select_observer(root,home)
    assert source['chain_id']=='new-chain' and source['rpc_url']=='http://127.0.0.1:27641'
    assert source['index_dir'].startswith('indexes/new-chain/')
    assert (root/'explorer/index/index.sqlite').read_bytes()==b'preserve-old-history'
    assert web.observer_source(root)==source
    assert web.observer_source(root)['chain_id']!='old-chain'


@pytest.mark.parametrize('fault',['id','chain','catching-up','pruned'])
def test_bad_full_source_fails_before_changing_selection(pinned_observer,fault):
    root,home,status=pinned_observer
    if fault=='id': status['node_info']['id']='b'*40
    if fault=='chain': status['node_info']['network']='wrong'
    if fault=='catching-up': status['sync_info']['catching_up']=True
    if fault=='pruned': status['sync_info']['earliest_block_height']='100'
    with pytest.raises(ValueError): web.select_observer(root,home)
    assert not (root/'explorer/observer.json').exists()
    assert (root/'explorer/index/index.sqlite').read_bytes()==b'preserve-old-history'


def test_tampered_saved_source_never_falls_back_to_legacy(pinned_observer):
    root,home,_=pinned_observer
    source=web.select_observer(root,home)
    path=root/'explorer/observer.json'
    path.write_text(json.dumps({**source,'rpc_url':'http://8.8.8.8:27641'}))
    with pytest.raises(ValueError): web.observer_source(root)
    path.write_text(json.dumps(source))
    (root/'explorer'/source['genesis_file']).write_text('{}')
    with pytest.raises(ValueError): web.observer_source(root)
