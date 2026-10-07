"""Operator/load regressions use fake RPC and scratch manifests, never host processes."""
import json
import os
from pathlib import Path
import hashlib

import pytest

from computechain.scripts import comet_load
from computechain.scripts.comet_devnet import Network, transaction_writer
from computechain.protocol.crypto.keys import public_key_from_private
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.blockchain.comet.transaction import decode


@pytest.fixture
def root(tmp_path):
    (tmp_path / "network.json").write_text(json.dumps({"chain_id": "unit-devnet", "base_port": 28600, "nodes": []}))
    (tmp_path / "processes.json").write_text("{}")
    return tmp_path


@pytest.fixture
def generator(root):
    value = comet_load.Generator(root, accounts=2, window=2, duration=1)
    value.wallets = []
    for i in range(2):
        key = hashlib.sha256(f"public-load-test-fixture-{i}".encode()).digest()
        value.wallets.append({"private_key": key.hex(), "address": address_from_pubkey(public_key_from_private(key)),
                              "next_nonce": 0, "inflight": 0})
    return value


@pytest.mark.parametrize("options", [{"tps": 0}, {"tps": 501}, {"duration": -1}, {"accounts": 1},
    {"accounts": 65}, {"window": 17}, {"amount": 0}, {"tps": float("nan")}])
def test_invalid_load_limits_fail_before_keys_or_rpc(root, options):
    with pytest.raises(ValueError):
        comet_load.Generator(root, **options)
    assert not (root / "load-wallets").exists()


def test_admission_is_not_confirmation_and_inflight_is_bounded(generator, monkeypatch):
    monkeypatch.setattr(comet_load, "rpc", lambda *args, **kwargs: {"code": 0})
    assert generator.submit(0) and generator.submit(0)
    assert not generator.submit(0)
    assert generator.report["submitted"] == 2 and generator.report["confirmed"] == 0
    nonces = [decode(record["raw"], "unit-devnet")["nonce"] for record in generator.pending.values()]
    assert nonces == [0, 1]
    assert generator.wallets[0]["next_nonce"] == 2


def test_checktx_rejection_does_not_advance_nonce(generator, monkeypatch):
    monkeypatch.setattr(comet_load, "rpc", lambda *args, **kwargs: {"code": 1, "log": "invalid nonce"})
    with pytest.raises(RuntimeError, match="CheckTx rejected"):
        generator.submit(0)
    assert generator.report["checktx_rejected"] == 1 and not generator.pending
    assert generator.wallets[0]["next_nonce"] == 0


def test_confirmation_checks_actual_execution_result(generator, monkeypatch):
    monkeypatch.setattr(comet_load, "rpc", lambda *args, **kwargs: {"code": 0})
    generator.submit(0)
    monkeypatch.setattr(comet_load, "rpc", lambda *args, **kwargs: {"tx_result": {"code": 0}, "height": "10"})
    generator.track()
    assert generator.report["confirmed"] == 1 and not generator.pending
    assert generator.wallets[0]["inflight"] == 0


def test_failed_execution_is_not_counted_as_success(generator, monkeypatch):
    monkeypatch.setattr(comet_load, "rpc", lambda *args, **kwargs: {"code": 0})
    generator.submit(0)
    monkeypatch.setattr(comet_load, "rpc", lambda *args, **kwargs: {"tx_result": {"code": 1}})
    with pytest.raises(RuntimeError, match="failed execution"):
        generator.track()
    assert generator.report["confirmed"] == 0 and generator.report["execution_failed"] == 1


def test_unknown_rpc_outcome_retries_exact_signed_bytes(generator, monkeypatch):
    def disconnected(*args, **kwargs):
        raise OSError("lost reply")
    monkeypatch.setattr(comet_load, "rpc", disconnected)
    generator.submit(0)
    assert generator.report["broadcast_errors"] == 1
    original = next(iter(generator.pending.values()))
    original["sent"] -= 6
    original["retry"] -= 6
    observed = []
    def retry(config, index, method, **params):
        if method == "tx":
            raise RuntimeError("not indexed yet")
        observed.append(params["tx"])
        return {"code": 0}
    monkeypatch.setattr(comet_load, "rpc", retry)
    generator.track()
    assert observed == ["0x" + original["raw"].hex()]
    assert generator.wallets[0]["next_nonce"] == 1


def test_writer_lock_excludes_other_tools_and_releases(root):
    with transaction_writer(root):
        with pytest.raises(RuntimeError, match="writer busy"):
            with transaction_writer(root):
                pass
    with transaction_writer(root):
        pass


def test_safe_stop_does_not_signal_unrelated_pid(root, monkeypatch):
    net = Network(root)
    (root / "processes.json").write_text(json.dumps({"load": {"pid": os.getpid(), "args": ["unrelated-command"]}}))
    signals = []
    monkeypatch.setattr(os, "kill", lambda *args: signals.append(args))
    net.stop("load")
    assert signals == []
    assert json.loads((root / "processes.json").read_text()) == {}


def test_reports_never_contain_private_wallets(generator):
    generator.save()
    report = (generator.net.root / "load-latest.json").read_text()
    assert "private_key" not in report
    assert all(wallet["private_key"] not in report for wallet in generator.wallets)
