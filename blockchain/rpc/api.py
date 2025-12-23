from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Optional, List
from ...protocol.types.tx import Transaction
from ...protocol.types.block import Block
from ...protocol.types.validator import Validator
from ..core.chain import Blockchain
from ..core.mempool import Mempool
import logging
import os

app = FastAPI(title="ComputeChain Node RPC")

# Enable CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
chain: Optional[Blockchain] = None
mempool: Optional[Mempool] = None

class TxResponse(BaseModel):
    tx_hash: str
    status: str

@app.get("/")
async def serve_dashboard():
    """Serve the dashboard HTML."""
    dashboard_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "dashboard.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    return {"message": "ComputeChain Node RPC", "version": "1.0"}

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

@app.get("/validator/{address}")
async def get_validator(address: str):
    """Get detailed validator information including performance metrics."""
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")
    val = chain.state.get_validator(address)
    if not val:
        raise HTTPException(status_code=404, detail="Validator not found")
    return val

@app.get("/validator/{address}/performance")
async def get_validator_performance(address: str):
    """Get validator performance statistics."""
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")
    val = chain.state.get_validator(address)
    if not val:
        raise HTTPException(status_code=404, detail="Validator not found")

    return {
        "address": val.address,
        "is_active": val.is_active,
        "performance_score": val.performance_score,
        "uptime_score": val.uptime_score,
        "blocks_proposed": val.blocks_proposed,
        "blocks_expected": val.blocks_expected,
        "missed_blocks": val.missed_blocks,
        "last_block_height": val.last_block_height,
        "power": val.power,
        "total_penalties": val.total_penalties,
        "jailed_until_height": val.jailed_until_height,
        "jail_count": val.jail_count,
        "joined_height": val.joined_height,
        "last_seen_height": val.last_seen_height
    }

@app.get("/delegator/{address}/delegations")
async def get_delegator_delegations(address: str):
    """Get all delegations for a specific delegator address."""
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    # Get all validators and find delegations from this delegator
    validators = chain.state.get_all_validators()
    delegations = []

    for val in validators:
        for delegation in val.delegations:
            if delegation.delegator == address:
                delegations.append({
                    "validator": delegation.validator,
                    "amount": delegation.amount,
                    "created_height": delegation.created_height,
                    "validator_name": val.name or "Unknown",
                    "validator_commission": val.commission_rate
                })

    return {
        "delegator": address,
        "delegations": delegations,
        "total_delegated": sum(d["amount"] for d in delegations)
    }

@app.get("/delegator/{address}/rewards")
async def get_delegator_rewards(address: str):
    """Get reward history for a specific delegator address."""
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    acc = chain.state.get_account(address)

    # Calculate total rewards
    total_rewards = sum(acc.reward_history.values())

    # Convert reward_history to a sorted list for easier display
    rewards_by_epoch = [
        {"epoch": epoch, "amount": amount}
        for epoch, amount in sorted(acc.reward_history.items())
    ]

    return {
        "delegator": address,
        "total_rewards": total_rewards,
        "rewards_by_epoch": rewards_by_epoch,
        "current_epoch": chain.state.epoch_index
    }

@app.get("/delegator/{address}/unbonding")
async def get_delegator_unbonding(address: str):
    """Get unbonding delegations for a specific delegator address."""
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    acc = chain.state.get_account(address)

    # Calculate total unbonding amount
    total_unbonding = sum(entry.amount for entry in acc.unbonding_delegations)

    # Convert unbonding_delegations to list with completion info
    unbonding_entries = [
        {
            "validator": entry.validator,
            "amount": entry.amount,
            "completion_height": entry.completion_height,
            "blocks_remaining": max(0, entry.completion_height - chain.height)
        }
        for entry in acc.unbonding_delegations
    ]

    return {
        "delegator": address,
        "total_unbonding": total_unbonding,
        "unbonding_count": len(acc.unbonding_delegations),
        "unbonding_delegations": unbonding_entries,
        "current_height": chain.height
    }

@app.get("/validators/leaderboard")
async def get_validators_leaderboard():
    """Get validators sorted by performance score."""
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    vals = chain.state.get_all_validators()

    # Sort by performance score
    sorted_vals = sorted(vals, key=lambda v: v.performance_score, reverse=True)

    leaderboard = []
    for rank, val in enumerate(sorted_vals, 1):
        leaderboard.append({
            "rank": rank,
            "address": val.address,
            "is_active": val.is_active,
            "performance_score": val.performance_score,
            "uptime_score": val.uptime_score,
            "power": val.power,
            "blocks_proposed": val.blocks_proposed,
            "blocks_expected": val.blocks_expected,
            "missed_blocks": val.missed_blocks,
            "jailed": val.jailed_until_height > chain.height,
            "jail_count": val.jail_count
        })

    return {
        "epoch": chain.state.epoch_index,
        "current_height": chain.height,
        "leaderboard": leaderboard
    }

@app.get("/validators/jailed")
async def get_jailed_validators():
    """Get list of currently jailed validators."""
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    vals = chain.state.get_all_validators()
    current_height = chain.height

    jailed = [
        {
            "address": v.address,
            "jailed_until_height": v.jailed_until_height,
            "blocks_remaining": max(0, v.jailed_until_height - current_height),
            "jail_count": v.jail_count,
            "total_penalties": v.total_penalties,
            "power": v.power
        }
        for v in vals
        if v.jailed_until_height > current_height
    ]

    return {
        "current_height": current_height,
        "jailed_count": len(jailed),
        "jailed_validators": jailed
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

        # Track transaction as pending (Phase 1.4)
        from blockchain.core.tx_receipt import tx_receipt_store
        tx_receipt_store.add_pending(tx.hash_hex)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"tx_hash": tx.hash_hex, "status": "received"}

@app.get("/tx/{tx_hash}/receipt")
async def get_tx_receipt(tx_hash: str):
    """
    Get transaction receipt (Phase 1.4).

    Returns transaction status: pending, confirmed, or failed.
    """
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    try:
        from blockchain.core.tx_receipt import tx_receipt_store

        receipt = tx_receipt_store.get(tx_hash)
        if not receipt:
            raise HTTPException(status_code=404, detail="Transaction not found")

        # Calculate confirmations if confirmed
        confirmations = None
        if receipt.status == 'confirmed' and receipt.block_height is not None:
            confirmations = tx_receipt_store.get_confirmations(tx_hash, chain.height)

        response = receipt.to_dict()
        if confirmations is not None:
            response['confirmations'] = confirmations

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Receipt error: {str(e)}")

@app.get("/metrics")
async def get_metrics():
    """
    Prometheus metrics endpoint (Phase 1.3).

    Returns metrics in Prometheus text format.
    """
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        from blockchain.observability.metrics import metrics_registry, update_metrics

        # Update metrics with current blockchain state
        update_metrics(chain, mempool)

        # Generate Prometheus metrics
        metrics_data = generate_latest(metrics_registry)

        return Response(
            content=metrics_data,
            media_type=CONTENT_TYPE_LATEST
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics error: {str(e)}")

# ═══════════════════════════════════════════════════════════════════
# SNAPSHOT ENDPOINTS (Phase 1.3)
# ═══════════════════════════════════════════════════════════════════

@app.get("/snapshots")
async def list_snapshots():
    """
    List all available snapshots.

    Returns:
        List of snapshot metadata (height, size, accounts, validators, etc.)
    """
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    if not chain.snapshot_manager:
        raise HTTPException(status_code=503, detail="Snapshots not enabled on this node")

    try:
        snapshots = chain.snapshot_manager.list_snapshots()
        return [snap.model_dump() for snap in snapshots]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Snapshot error: {str(e)}")

@app.get("/snapshots/{height}")
async def get_snapshot_info(height: int):
    """
    Get metadata for a specific snapshot.

    Args:
        height: Block height of snapshot

    Returns:
        Snapshot metadata
    """
    if not chain:
        raise HTTPException(status_code=503, detail="Node not initialized")

    if not chain.snapshot_manager:
        raise HTTPException(status_code=503, detail="Snapshots not enabled on this node")

    try:
        snapshots = chain.snapshot_manager.list_snapshots()
        for snap in snapshots:
            if snap.height == height:
                return snap.model_dump()

        raise HTTPException(status_code=404, detail=f"Snapshot at height {height} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Snapshot error: {str(e)}")

def start_rpc_server(blockchain_instance: Blockchain, mempool_instance: Mempool, host: str = "0.0.0.0", port: int = 8000):
    global chain, mempool
    chain = blockchain_instance
    mempool = mempool_instance
    import uvicorn
    uvicorn.run(app, host=host, port=port)
