from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import Optional, List
from ...protocol.types.tx import Transaction
from ...protocol.types.block import Block
from ...protocol.types.validator import Validator
from ..core.chain import Blockchain
from ..core.mempool import Mempool
import logging

app = FastAPI(title="ComputeChain Node RPC")
chain: Optional[Blockchain] = None
mempool: Optional[Mempool] = None

class TxResponse(BaseModel):
    tx_hash: str
    status: str

@app.get("/status")
async def get_status():
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")
    return {
        "height": chain.height,
        "last_hash": chain.last_hash,
        "network": chain.config.network_id,
        "mempool_size": mempool.size() if mempool else 0,
        "epoch": chain.state.epoch_index
    }

@app.get("/block/{height}")
async def get_block(height: int):
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")
    block = chain.get_block(height)
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    return block

@app.get("/balance/{address}")
async def get_balance(address: str):
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")
    acc = chain.state.get_account(address)
    return {
        "address": address,
        "balance": str(acc.balance),
        "nonce": acc.nonce
    }

@app.get("/validators")
async def get_validators():
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")
    vals = chain.state.get_all_validators()
    return {
        "epoch": chain.state.epoch_index,
        "validators": vals
    }

@app.post("/tx/send")
async def send_tx(tx: Transaction):
    if not chain or not mempool:
        raise HTTPException(status_code=503, detail="Node not initialized")
    
    try:
        # Basic validation via Mempool
        added, reason = mempool.add_transaction(tx)
        if not added:
             return {"tx_hash": tx.hash_hex, "status": "rejected", "error": reason}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"tx_hash": tx.hash_hex, "status": "received"}

def start_rpc_server(blockchain_instance: Blockchain, mempool_instance: Mempool, host: str = "0.0.0.0", port: int = 8000):
    global chain, mempool
    chain = blockchain_instance
    mempool = mempool_instance
    import uvicorn
    uvicorn.run(app, host=host, port=port)
