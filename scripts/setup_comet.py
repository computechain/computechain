#!/usr/bin/env python3
"""Reproducible local tool setup; no global installation or node-data resets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

TAG = "v0.40.0"
COMMIT = "0880b4d378f347ab16e54ec677ff50d803f37d62"
GO_VERSION = "1.26.8"
GO_SHA = "d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b"
GOGO_SHA = "a2bef0fb7e233ff2f442da08b3764be6ce59cc3f2df05cd1c9a44dbb5b55c18f"


def fetch(url, destination, digest):
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    with urllib.request.urlopen(url, timeout=60) as source, temporary.open("wb") as output:
        shutil.copyfileobj(source, output)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
        raise RuntimeError("upstream download checksum mismatch")
    temporary.replace(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    tools = (args.tools or repo.parent / ".tools").resolve()
    source = tools / "src/cometbft"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", TAG, "https://github.com/cometbft/cometbft.git", str(source)], check=True)
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT or subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("CometBFT checkout is not the clean pinned source")
    go = tools / "go/bin/go"
    if not go.exists():
        archive = tools / "downloads" / f"go{GO_VERSION}.linux-amd64.tar.gz"
        fetch(f"https://go.dev/dl/go{GO_VERSION}.linux-amd64.tar.gz", archive, GO_SHA)
        with tarfile.open(archive) as bundle:
            bundle.extractall(tools, filter="data")
    if f"go{GO_VERSION}" not in subprocess.check_output([str(go), "version"], text=True):
        raise RuntimeError("unexpected Go toolchain")
    binary = tools / "bin/cometbft"
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(go), "build", "-p", "2", "-trimpath", "-ldflags",
        "-X github.com/cometbft/cometbft/version.TMGitCommitHash=" + COMMIT,
        "-o", str(binary), "./cmd/cometbft"], cwd=source,
        env={**os.environ, "GOMAXPROCS": "2", "GOPATH": str(tools / "go-cache")}, check=True)
    env = tools / "blockchain-venv"
    if not (env / "bin/python").exists():
        # Some Debian hosts lack ensurepip but leave a usable pip-less venv.
        created = subprocess.run([sys.executable, "-m", "venv", str(env)])
        if created.returncode and not (env / "bin/python").exists():
            raise RuntimeError("install python3-venv first")
    pip = shutil.which("pip") or shutil.which("pip3")
    if not pip:
        raise RuntimeError("a pip supporting --python is required")
    subprocess.run([pip, "--python", str(env), "install", "-r", str(repo / "requirements-comet.txt")], check=True)
    gogo = tools / "proto-deps/gogoproto/gogo.proto"
    fetch("https://raw.githubusercontent.com/cosmos/gogoproto/v1.7.2/gogoproto/gogo.proto", gogo, GOGO_SHA)
    subprocess.run([str(env / "bin/python"), str(repo / "scripts/generate_abci.py"), "--upstream", str(source), "--gogo", str(gogo)], check=True)
    metadata = {"source_tag": TAG, "source_commit": COMMIT, "go_version": GO_VERSION,
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "binary_version_output": subprocess.check_output([str(binary), "version"], text=True).strip()}
    (tools / "comet-build.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
