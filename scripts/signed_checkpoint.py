"""Domain-separated operator attestations; native Comet remains the light verifier."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
from ecdsa import Ed25519,SigningKey,VerifyingKey
from computechain.blockchain.comet.transaction import canonical
from computechain.scripts import comet_checkpoint as anchors

DOMAIN=b'ComputeChain/checkpoint-attestation/v1\0'


def key_init(path):
    path=Path(path)
    if path.exists() or path.is_symlink(): raise ValueError('authority key already exists; no overwrite')
    raw=os.urandom(32)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as stream:
        stream.write(raw.hex()); stream.flush(); os.fsync(stream.fileno())
    public=SigningKey.from_string(raw,curve=Ed25519).verifying_key.to_string().hex()
    return {'public_key':public,'public_key_sha256':hashlib.sha256(bytes.fromhex(public)).hexdigest()}


def sign(path,checkpoint,config):
    anchors.validate(checkpoint,config)
    path=Path(path)
    if path.is_symlink() or path.stat().st_mode&0o077: raise ValueError('operator key must be private, non-symlink')
    signer=SigningKey.from_string(bytes.fromhex(path.read_text()),curve=Ed25519)
    return {'format':1,'checkpoint':checkpoint,'authority':signer.verifying_key.to_string().hex(),
            'signature':signer.sign(DOMAIN+canonical(checkpoint)).hex()}


def verify_signature(envelope,approved_public):
    if not isinstance(approved_public,str) or not re.fullmatch(r'[0-9a-f]{64}',approved_public):
        raise ValueError('explicit operator public key required')
    if not isinstance(envelope,dict) or set(envelope)!={'format','checkpoint','authority','signature'} or type(envelope['format']) is not int or envelope['format']!=1 or envelope['authority']!=approved_public:
        raise ValueError('unapproved checkpoint authority/format')
    from computechain.blockchain.comet.staking import consensus_key
    consensus_key(approved_public)
    try:
        signature=envelope['signature']
        if not isinstance(signature,str) or not re.fullmatch(r'[0-9a-f]{128}',signature): raise ValueError
        key=VerifyingKey.from_string(bytes.fromhex(approved_public),curve=Ed25519)
        if not key.verify(bytes.fromhex(signature),DOMAIN+canonical(envelope['checkpoint'])): raise ValueError
    except Exception as exc: raise ValueError('invalid operator checkpoint signature') from exc
    return envelope['checkpoint']


def verify(envelope,approved_public,config,now_ns=None):
    checkpoint=verify_signature(envelope,approved_public)
    anchors.validate(checkpoint,config,now_ns=now_ns)
    return checkpoint


def load(path):
    with Path(path).open('rb') as stream: raw=stream.read(anchors.MAX_FILE_BYTES+1)
    if len(raw)>anchors.MAX_FILE_BYTES: raise ValueError('signed checkpoint file too large')
    return json.loads(raw,object_pairs_hook=anchors._unique_pairs)


def export(path,envelope):
    anchors.export(path,envelope)  # same bounded, atomic no-overwrite transport
