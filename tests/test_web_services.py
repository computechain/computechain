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
