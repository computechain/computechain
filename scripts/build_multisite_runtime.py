#!/usr/bin/env python3
"""Build a compact public-source runtime with predownloaded binary wheels, locally."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

REPO=Path(__file__).resolve().parents[1]


def build(wheels,output):
    if output.exists() or output.is_symlink(): raise ValueError('runtime output must be NEW')
    runtime=output/'runtime'
    runtime.mkdir(parents=True)
    files=list((REPO/'blockchain/comet').rglob('*.py'))+list((REPO/'protocol/crypto').glob('*.py'))
    files += [REPO/p for p in ('__init__.py','blockchain/__init__.py','protocol/__init__.py')]
    files += [REPO/'scripts'/p for p in ('multisite.py','comet_devnet.py','comet_checkpoint.py','rpc_read_gateway.py','install_multisite.py','fleet_node.py','fleet_network.py')]
    files += [REPO/'scripts'/p for p in ('bootstrap_read_service.py','bootstrap_pki.py','signed_checkpoint.py','bootstrap_protocol.py','bootstrap_follower.py','install_bootstrap_read.py')]
    for source in files:
        target=runtime/'computechain'/source.relative_to(REPO)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    tools=runtime/'.tools'
    (tools/'bin').mkdir(parents=True)
    shutil.copyfile(REPO.parent/'.tools/bin/cometbft',tools/'bin/cometbft')
    (tools/'bin/cometbft').chmod(0o755)
    shutil.copyfile(REPO.parent/'.tools/comet-build.json',tools/'comet-build.json')
    shutil.copyfile(REPO/'deploy/openssl-runtime.cnf',runtime/'openssl.cnf')
    deps=runtime/'.deps'; deps.mkdir()
    hashes={}
    for wheel in sorted(wheels.glob('*.whl')):
        hashes[wheel.name]=hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            for entry in archive.infolist():
                path=Path(entry.filename)
                if path.is_absolute() or '..' in path.parts: raise ValueError('unsafe wheel member')
            archive.extractall(deps)
    if not hashes: raise ValueError('downloaded binary wheels are required')
    (runtime/'wheel-sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    with tarfile.open(output/'runtime.tar.gz','w:gz') as archive:
        archive.add(runtime,arcname='runtime')
    return {'archive':str(output/'runtime.tar.gz'),'sha256':hashlib.sha256((output/'runtime.tar.gz').read_bytes()).hexdigest(),'wheels':hashes}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(build(args.wheels,args.output),indent=2))


if __name__=='__main__': main()
