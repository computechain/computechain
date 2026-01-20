import pytest
import json
import time
import tempfile
import shutil
import os
from computechain.blockchain.core.chain import Blockchain
from computechain.protocol.config.params import NetworkConfig
from computechain.protocol.types.block import Block, BlockHeader
from computechain.protocol.crypto.keys import generate_private_key, public_key_from_private, sign
from computechain.protocol.crypto.addresses import address_from_pubkey
from computechain.protocol.types.validator import Validator, ValidatorSet

@pytest.fixture
def chain_setup():
    temp_dir = tempfile.mkdtemp()
    genesis_path = os.path.join(temp_dir, "genesis.json")
    with open(genesis_path, "w") as f:
        json.dump({"alloc": {}, "validators": [], "genesis_time": int(time.time()) - 100}, f)
    config = NetworkConfig(
        network_id="testnet",
        chain_id="computechain-1",
        min_gas_price=1,
        max_tx_per_block=100,
        genesis_premine=100000,
        block_time_sec=1,
        epoch_length_blocks=10,
        min_validator_stake=100,
        max_validators=5,
        block_gas_limit=10_000_000
    )
    
    db_path = os.path.join(temp_dir, "chain.db")
    chain = Blockchain(db_path)
    chain.config = config # Override global config with test config
    
    # Create validator keys
    priv = generate_private_key()
    pub = public_key_from_private(priv)
    addr = address_from_pubkey(pub, prefix="cpcvalcons")
    
    # Inject validator manually into state and consensus
    val = Validator(address=addr, pq_pub_key=pub.hex(), power=1000, is_active=True)
    
    chain.state.set_validator(val)
    chain.consensus.validator_set = ValidatorSet(validators=[val], total_power=1000)
    
    # Mock chain state to height 10
    chain.height = 10
    chain.last_block_timestamp = chain.genesis_time + (chain.height * config.block_time_sec)
    chain.last_hash = "0"*64
    
    yield chain, priv, addr
    
    shutil.rmtree(temp_dir)

def test_block_signature_valid(chain_setup):
    chain, priv, val_addr = chain_setup
    
    # Prepare next block parameters
    next_height = chain.height + 1 # 11
    timestamp = chain.genesis_time + (next_height * chain.config.block_time_sec)
    
    header = BlockHeader(
        height=next_height,
        prev_hash=chain.last_hash,
        timestamp=timestamp,
        chain_id="computechain-1",
        proposer_address=val_addr,
        round=0,
        tx_root="0"*64,
        state_root=chain.state.compute_state_root()
    )
    
    # Sign
    sig = sign(bytes.fromhex(header.hash()), priv).hex()
    block = Block(header=header, txs=[], pq_signature=sig)
    
    # Should pass
    assert chain.add_block(block) is True

def test_block_signature_invalid(chain_setup):
    chain, priv, val_addr = chain_setup
    
    header = BlockHeader(
        height=chain.height + 1,
        prev_hash=chain.last_hash,
        timestamp=chain.genesis_time + ((chain.height + 1) * chain.config.block_time_sec),
        chain_id="computechain-1",
        proposer_address=val_addr,
        round=0,
        tx_root="0"*64,
        state_root=chain.state.compute_state_root()
    )
    
    # Sign with WRONG key
    wrong_priv = generate_private_key()
    sig = sign(bytes.fromhex(header.hash()), wrong_priv).hex()
    block = Block(header=header, txs=[], pq_signature=sig)
    
    with pytest.raises(ValueError, match="Invalid block PQ signature"):
        chain.add_block(block)

def test_block_signature_missing(chain_setup):
    chain, priv, val_addr = chain_setup
    
    header = BlockHeader(
        height=chain.height + 1,
        prev_hash=chain.last_hash,
        timestamp=chain.genesis_time + ((chain.height + 1) * chain.config.block_time_sec),
        chain_id="computechain-1",
        proposer_address=val_addr,
        round=0,
        tx_root="0"*64,
        state_root=chain.state.compute_state_root()
    )
    
    block = Block(header=header, txs=[], pq_signature="")
    
    with pytest.raises(ValueError, match="Missing block PQ signature"):
        chain.add_block(block)

def test_block_future_timestamp(chain_setup):
    chain, priv, val_addr = chain_setup
    
    # Future timestamp (more than 15s)
    future_ts = int(time.time()) + 1000
    
    header = BlockHeader(
        height=chain.height + 1,
        prev_hash=chain.last_hash,
        timestamp=future_ts,
        chain_id="computechain-1",
        proposer_address=val_addr,
        round=0,
        tx_root="0"*64,
        state_root=chain.state.compute_state_root()
    )
    
    # Sign
    sig = sign(bytes.fromhex(header.hash()), priv).hex()
    block = Block(header=header, txs=[], pq_signature=sig)
    
    with pytest.raises(ValueError, match="Invalid timestamp for slot"):
        chain.add_block(block)
