#!/usr/bin/env python3
"""Generate Python protobuf/gRPC bindings from the pinned upstream protocol."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys

COMMIT = "0880b4d378f347ab16e54ec677ff50d803f37d62"
PREFIX = "computechain.blockchain.comet.proto"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--gogo", type=Path, required=True)
    args = parser.parse_args()
    actual = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT:
        raise SystemExit("unexpected CometBFT source commit")
    root = Path(__file__).resolve().parents[1]
    source = root / "blockchain/comet/proto_src"
    output = root / "blockchain/comet/proto"
    paths = ["tendermint/abci/types.proto", "tendermint/crypto/keys.proto", "tendermint/crypto/proof.proto",
             "tendermint/types/params.proto", "tendermint/types/validator.proto", "gogoproto/gogo.proto"]
    for name in paths:
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        origin = args.gogo if name.startswith("gogoproto/") else args.upstream / "proto" / name
        shutil.copyfile(origin, destination)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.upstream / "LICENSE", source / "COMETBFT_LICENSE")
    import grpc_tools
    include = Path(grpc_tools.__file__).parent / "_proto"
    subprocess.run([sys.executable, "-m", "grpc_tools.protoc", "-I" + str(source), "-I" + str(include),
                    "--python_out=" + str(output), "--grpc_python_out=" + str(output), *[str(source / p) for p in paths]], check=True)
    for file in output.rglob("*.py"):
        content = file.read_text()
        content = re.sub(r"^from (tendermint|gogoproto)([.\w]*) import ", rf"from {PREFIX}.\1\2 import ", content, flags=re.M)
        file.write_text(content)
    for directory in [output, *[p for p in output.rglob("*") if p.is_dir()]]:
        (directory / "__init__.py").touch()
    print("Generated pinned CometBFT v0.40.0 ABCI bindings")


if __name__ == "__main__":
    main()
