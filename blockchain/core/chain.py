# MIT License
# Copyright (c) 2025 Hashborn

from typing import Optional, List, Dict
import time
import logging
import os
import json
import threading
from ...protocol.types.block import Block, BlockHeader
from ...protocol.types.tx import Transaction
from ...protocol.types.poc import ComputeResult
from ...protocol.types.common import TxType
from ...protocol.crypto.keys import verify
from ...protocol.crypto import pq
from ...protocol.crypto.hash import sha256
from ...protocol.crypto.addresses import address_from_pubkey
from ...protocol.types.validator import Validator, ValidatorSet
from ...protocol.config.params import CURRENT_NETWORK, GAS_PER_TYPE
from ..storage.db import StorageDB
from .state import AccountState
from .accounts import Account
from .rewards import calculate_block_reward
from ..consensus.engine import ConsensusEngine
from .events import event_bus  # Import at module level!
from .tx_receipt import tx_receipt_store  # Import at module level!

logger = logging.getLogger(__name__)

class Blockchain:
    def __init__(self, db_path: str, enable_snapshots: bool = True, snapshot_interval: int = 1000):
        self.db = StorageDB(db_path)
        self._lock = threading.RLock()
        self.state = AccountState(self.db)
        self.state.load_epoch_info()
        self.config = CURRENT_NETWORK

        # Try to load genesis allocation if chain is empty
        self.genesis_path = os.path.join(os.path.dirname(db_path), "genesis.json")

        # Initialize Consensus Engine
        self.consensus = ConsensusEngine()

        # Initialize Snapshot Manager (Phase 1.3)
        self.enable_snapshots = enable_snapshots
        self.snapshot_interval = snapshot_interval  # Create snapshot every N blocks
        if enable_snapshots:
            from ..snapshot import SnapshotManager
            snapshots_dir = os.path.join(os.path.dirname(db_path), "snapshots")
            self.snapshot_manager = SnapshotManager(snapshots_dir)
            logger.info(f"Snapshot system enabled (interval: {snapshot_interval} blocks)")
        else:
            self.snapshot_manager = None

        self.last_block_timestamp = 0
        self._load_chain_state()

    def _load_chain_state(self):
        last = self.db.get_last_block()
        if last:
            self.height, self.last_hash, _ = last
            # Load timestamp of last block for consensus
            last_blk = self.get_block(self.height)
            if last_blk:
                self.last_block_timestamp = last_blk.header.timestamp

            logger.info(f"Chain initialized at height {self.height}")
            self._update_consensus_from_state()
        else:
            self.height = -1
            self.last_hash = "0" * 64
            self.last_block_timestamp = 0
            logger.info("Chain initialized empty (waiting for genesis)")
            self._apply_genesis_allocation()
            self._apply_genesis_validators()

    def load_from_snapshot(self, snapshot_height: int) -> bool:
        """
        Load blockchain state from a snapshot (Phase 1.3 - Fast Sync).

        This allows a new node to quickly sync by loading a snapshot
        and then syncing only the remaining blocks.

        Args:
            snapshot_height: Height of snapshot to load

        Returns:
            True if successful, False otherwise

        Raises:
            FileNotFoundError: If snapshot doesn't exist
            ValueError: If snapshot verification fails
        """
        if not self.snapshot_manager:
            raise RuntimeError("Snapshot system not enabled")

        logger.info(f"Loading blockchain state from snapshot at height {snapshot_height}...")

        # Load snapshot
        snapshot = self.snapshot_manager.load_snapshot(snapshot_height)

        # Verify snapshot is for correct network
        if snapshot.network_id != self.config.network_id:
            raise ValueError(
                f"Snapshot network mismatch: expected {self.config.network_id}, "
                f"got {snapshot.network_id}"
            )

        # Apply snapshot to state
        self.snapshot_manager.apply_snapshot(snapshot, self.state)

        # Update chain height from snapshot
        # We need to find the block at snapshot height to set last_hash
        snapshot_block = self.get_block(snapshot_height)
        if snapshot_block:
            self.height = snapshot_height
            self.last_hash = snapshot_block.hash()
            self.last_block_timestamp = snapshot_block.header.timestamp
        else:
            # If block doesn't exist in DB, we still set height but with placeholder hash
            # The node will need to sync blocks from snapshot_height onwards
            self.height = snapshot_height
            self.last_hash = "0" * 64  # Placeholder
            self.last_block_timestamp = 0
            logger.warning(
                f"Snapshot loaded but block {snapshot_height} not in DB. "
                f"You may need to sync blocks from a peer."
            )

        # Update consensus with validator set from snapshot
        self._update_consensus_from_state()

        logger.info(
            f"Fast sync complete! Chain state loaded from snapshot at height {snapshot_height}"
        )
        return True

    def fast_sync_from_latest_snapshot(self) -> bool:
        """
        Fast sync from the most recent available snapshot.

        Returns:
            True if successful, False if no snapshots available
        """
        if not self.snapshot_manager:
            logger.warning("Snapshot system not enabled, skipping fast sync")
            return False

        latest_height = self.snapshot_manager.get_latest_snapshot_height()

        if latest_height is None:
            logger.info("No snapshots available for fast sync")
            return False

        logger.info(f"Found snapshot at height {latest_height}, initiating fast sync...")

        try:
            self.load_from_snapshot(latest_height)
            return True
        except Exception as e:
            logger.error(f"Fast sync failed: {e}")
            return False

    def get_latest_snapshot_height(self) -> Optional[int]:
        """Returns latest snapshot height if snapshot system is enabled."""
        if not self.snapshot_manager:
            return None
        return self.snapshot_manager.get_latest_snapshot_height()

    def get_snapshot_bytes(self, height: int) -> Optional[bytes]:
        """Returns raw snapshot file bytes (gzip) for a given height."""
        if not self.snapshot_manager:
            return None
        snapshot_path = self.snapshot_manager._get_snapshot_path(height)
        if not snapshot_path.exists():
            return None
        try:
            return snapshot_path.read_bytes()
        except Exception:
            return None

    def load_snapshot_from_bytes(self, height: int, data: bytes) -> bool:
        """Save snapshot bytes and load state from it."""
        if not self.snapshot_manager:
            return False
        try:
            self.snapshot_manager.save_snapshot_bytes(height, data)
            return self.load_from_snapshot(height)
        except Exception as e:
            logger.error(f"Failed to load snapshot from bytes: {e}")
            return False

    # --- Thread-safe wrappers ---
    def add_block(self, block: Block) -> bool:
        with self._lock:
            return self._add_block_impl(block)

    def rollback_last_block(self):
        with self._lock:
            self._rollback_last_block_impl()

    def rollback_to_height(self, target_height: int):
        with self._lock:
            self._rollback_to_height_impl(target_height)

    def rebuild_state_from_blocks(self):
        with self._lock:
            self._rebuild_state_from_blocks_impl()

    def _update_consensus_from_state(self):
        """Refreshes consensus engine from current state validators."""
        validators = self.state.get_all_validators()
        if validators:
            self.consensus.update_validator_set(validators)
        else:
            # Fallback to genesis if state is empty (should not happen on restart if persisted)
            self._apply_genesis_validators()

    def _apply_genesis_allocation(self):
        """Loads initial balances from genesis.json if exists."""
        if not os.path.exists(self.genesis_path):
            logger.warning("No genesis.json found. Starting with 0 balances.")
            return

        try:
            with open(self.genesis_path, "r") as f:
                data = json.load(f)
            
            # Parse allocation
            alloc = data.get("alloc", {})
            # Backwards compatibility
            if not "alloc" in data and not "validators" in data:
                 alloc = data
            
            count = 0
            for address, amount in alloc.items():
                acc = self.state.get_account(address)
                acc.balance = int(amount)
                self.state.set_account(acc)
                count += 1
            
            # Persist genesis state
            self.state.persist()
            logger.info(f"Applied genesis allocation to {count} accounts.")
        except Exception as e:
            logger.error(f"Failed to apply genesis allocation: {e}")

    def _apply_genesis_validators(self):
        """Loads initial validators from genesis.json."""
        if not os.path.exists(self.genesis_path):
            return

        try:
            with open(self.genesis_path, "r") as f:
                data = json.load(f)
                
            val_data = data.get("validators", [])
            if val_data:
                validators = []
                for v in val_data:
                    # Fix for 'pub_key' -> 'pq_pub_key' migration in genesis
                    if "pub_key" in v and "pq_pub_key" not in v:
                        v["pq_pub_key"] = v.pop("pub_key")
                    
                    val_obj = Validator(**v)
                    # Save to state too!
                    self.state.set_validator(val_obj)
                    validators.append(val_obj)
                
                self.state.persist()
                self.consensus.update_validator_set(validators)
                logger.info(f"Loaded {len(validators)} genesis validators.")
                
        except Exception as e:
             logger.error(f"Failed to load genesis validators: {e}")

    @property
    def genesis_hash(self) -> Optional[str]:
        """Returns hash of block 0 if exists."""
        if self.height < 0:
            return None
        blk = self.get_block(0)
        return blk.hash() if blk else None

    @property
    def last_block_hash(self) -> Optional[str]:
        """Returns hash of the last block or None if empty."""
        if self.height < 0:
            return None
        return self.last_hash

    def get_blocks_range(self, from_height: int, to_height: int) -> List[Block]:
        """Returns blocks in range [from_height, to_height] inclusive."""
        blocks = []
        # Sanity check
        if from_height < 0: from_height = 0
        
        for h in range(from_height, to_height + 1):
            blk = self.get_block(h)
            if blk:
                blocks.append(blk)
            else:
                break # Stop if gap found (should not happen if requesting <= height)
        return blocks

    def get_headers_range(self, from_height: int, to_height: int) -> List[BlockHeader]:
        """Returns block headers in range [from_height, to_height] inclusive."""
        headers = []
        if from_height < 0:
            from_height = 0

        for h in range(from_height, to_height + 1):
            blk = self.get_block(h)
            if blk:
                headers.append(blk.header)
            else:
                break
        return headers


    def _add_block_impl(self, block: Block) -> bool:
        # 1. Basic Validation
        if block.header.height != self.height + 1:
            # Check if we already have this block (idempotency for sync)
            if block.header.height <= self.height:
                existing = self.get_block(block.header.height)
                if existing and existing.hash() == block.hash():
                    return True # Already have it
                
            raise ValueError(f"Invalid height: expected {self.height + 1}, got {block.header.height}")
        
        if block.header.prev_hash != self.last_hash and self.height >= 0:
             raise ValueError(f"Invalid prev_hash: expected {self.last_hash[:8]}, got {block.header.prev_hash[:8]}")

        # 2. Consensus Validation (Proposer Check with Round Logic)
        # Calculate round based on timestamp
        last_ts = self.last_block_timestamp
        current_ts = block.header.timestamp
        block_time = self.config.block_time_sec
        
        if current_ts <= last_ts:
             # Unless it's genesis or very fast local test? No, blocks must move forward in time.
             # Allow equality only if it's the very first block? No.
             if self.height >= 0:
                 # Relax check for devnet reorgs? No, timestamps must increase.
                 raise ValueError(f"Invalid timestamp: must be > {last_ts}")
        
        # P1.3: Future Drift Check
        # Allow up to 15 seconds drift
        if current_ts > time.time() + 15:
             raise ValueError(f"Block timestamp too far in future: {current_ts} > now+15s")
        
        # Round 0: (current - last) <= block_time (roughly)
        # Actually: 
        # Expected TS for Round 0 = last_ts + block_time
        # Expected TS for Round 1 = last_ts + 2*block_time
        
        # We can infer round:
        if self.height == -1:
            # Genesis / First block
            round = 0
        else:
            diff = current_ts - last_ts
            if diff < block_time:
                 # Too early? For devnet we might accept, but strictly speaking:
                 # raise ValueError("Block timestamp too early")
                 round = 0
            else:
                 round = int((diff - block_time) // block_time)

        expected_proposer = self.consensus.get_proposer(block.header.height, round)
        
        if expected_proposer:
            if block.header.proposer_address != expected_proposer.address:
                 # Try next round? Maybe the node thought it was round N, but network thinks N+1?
                 # Strict check:
                 raise ValueError(f"Invalid proposer for round {round}: expected {expected_proposer.address}, got {block.header.proposer_address}")
            
            # Verify Block Signature (PQ)
            if not block.pq_signature:
                raise ValueError("Missing block PQ signature")
            
            try:
                blk_hash_bytes = bytes.fromhex(block.header.hash())
                sig_bytes = bytes.fromhex(block.pq_signature)
                pub_bytes = bytes.fromhex(expected_proposer.pq_pub_key)
                
                if not pq.verify(blk_hash_bytes, sig_bytes, pub_bytes):
                    raise ValueError("Invalid block PQ signature")
            except Exception as e:
                # Re-raise as ValueError for consistency
                raise ValueError(f"Block signature verification failed: {e}")

        else:
            if self.consensus.validator_set.validators:
                raise ValueError("Could not determine expected proposer")
            else:
                logger.warning("No validators in set! Accepting block from anyone (Bootstrap mode).")

        # 3. Simulation / Validate Transactions
        # NOTE: Performance tracking moved to AFTER state validation to avoid
        # state_root mismatch. The proposer doesn't include tracking updates
        # when computing state_root, so validators shouldn't either.
        tmp_state = self.state.clone()
        
        valid_txs = []
        cumulative_gas = 0
        
        for tx in block.txs:
            try:
                tmp_state.apply_transaction(tx, current_height=block.header.height, skip_crypto_check=False)
                valid_txs.append(tx)
                cumulative_gas += GAS_PER_TYPE.get(tx.tx_type, 0)
            except Exception as e:
                logger.error(f"Tx {tx.hash()} failed: {e}")
                raise e 

        # Check Gas
        if cumulative_gas != block.header.gas_used:
            raise ValueError(f"Gas used mismatch: expected {block.header.gas_used}, calculated {cumulative_gas}")
        
        if block.header.gas_limit > self.config.block_gas_limit:
             raise ValueError(f"Block gas limit exceeds network max: {block.header.gas_limit} > {self.config.block_gas_limit}")
        
        if cumulative_gas > block.header.gas_limit:
             raise ValueError(f"Gas used exceeds block limit: {cumulative_gas} > {block.header.gas_limit}")

        # 4. Check State Root
        calculated_root = tmp_state.compute_state_root()
        if block.header.state_root != calculated_root:
            logger.warning(f"State root mismatch: expected {block.header.state_root}, got {calculated_root}")
            raise ValueError(f"State root mismatch")

        # Check Compute Root (PoC)
        calculated_poc_root = self.compute_poc_root(block.txs)
        if block.header.compute_root != calculated_poc_root:
             raise ValueError(f"Compute root mismatch: expected {block.header.compute_root}, got {calculated_poc_root}")
        
        # 5. Epoch Management (New Logic!)
        # Check if this block ends an epoch
        if (block.header.height + 1) % self.config.epoch_length_blocks == 0:
            logger.info(f"End of Epoch {tmp_state.epoch_index}. Recalculating validators...")
            self._process_epoch_transition(tmp_state)
            
            # Log active set
            # We need to see who is active in tmp_state now
            active = [v.address for v in tmp_state.get_all_validators() if v.is_active]
            logger.info(f"New Validator Set: {active}")

        # 6. Apply Real
        self.state = tmp_state

        # 6.1 Distribute Rewards (Block Reward + Fees)
        self._distribute_rewards(block, self.state)

        # 6.2 Process Unbonding Queue (Phase 1.2)
        self.state.process_unbonding_queue(block.header.height)

        # 6.3 Track Performance (Phase 0)
        # NOTE: This is done AFTER state validation and state assignment
        # to avoid state_root mismatch. The proposer doesn't include tracking
        # updates when computing state_root. These updates are NOT part of
        # consensus but are used locally for validator scoring at epoch boundaries.
        self._track_proposer_performance(block)
        self._track_missed_blocks(block)

        # 7. Persist
        self.state.persist()
        self.db.save_block(block.header.height, block.hash(), block.model_dump_json())
        
        # 8. Update Consensus Engine with new state
        # We reload from state to ensure consistency
        if (block.header.height + 1) % self.config.epoch_length_blocks == 0:
             self._update_consensus_from_state()

        self.height = block.header.height
        self.last_hash = block.hash()
        self.last_block_timestamp = block.header.timestamp # Update TS

        # Update Prometheus metrics (Phase 1.3)
        try:
            from blockchain.observability.metrics import update_metrics, update_block_metrics, update_block_transaction_count, update_transaction_metrics
            update_block_metrics(self)  # Update counters/histograms (only on block add)
            update_metrics(self)  # Update gauges
            update_block_transaction_count(len(block.txs))  # Update tx histogram
            # Update transaction counter for each tx in block
            for tx in block.txs:
                update_transaction_metrics(tx)
        except Exception as e:
            logger.warning(f"Failed to update metrics: {e}")

        # Emit transaction confirmation events (Phase 1.4)
        try:
            # event_bus and tx_receipt_store are now imported at module level

            # Log EventBus state for debugging (only once per block)
            if block.txs:
                logger.info(f"Block {block.header.height}: EventBus ID={id(event_bus)}, listeners={list(event_bus.listeners.keys())}, tx_confirmed_count={len(event_bus.listeners.get('tx_confirmed', []))}")

            for tx in block.txs:
                # Mark transaction as confirmed in receipt store
                tx_receipt_store.mark_confirmed(tx.hash(), block.header.height)
                # Emit event for subscribers (e.g., NonceManager)
                event_bus.emit('tx_confirmed',
                              tx_hash=tx.hash(),
                              block_height=block.header.height,
                              tx=tx)
        except Exception as e:
            logger.warning(f"Failed to emit tx_confirmed events: {e}")

        # Create snapshot if enabled (Phase 1.3)
        if self.enable_snapshots and self.snapshot_manager:
            should_snapshot = False

            # Snapshot at epoch boundaries
            if (block.header.height + 1) % self.config.epoch_length_blocks == 0:
                should_snapshot = True
                logger.info(f"Creating snapshot at epoch boundary (height {block.header.height})")

            # Snapshot every N blocks
            elif self.snapshot_interval > 0 and block.header.height % self.snapshot_interval == 0:
                should_snapshot = True
                logger.info(f"Creating snapshot at interval (height {block.header.height})")

            if should_snapshot:
                try:
                    self.snapshot_manager.create_snapshot(
                        state=self.state,
                        height=block.header.height,
                        network_id=self.config.network_id
                    )
                    # Cleanup old snapshots (keep last 10)
                    self.snapshot_manager.cleanup_old_snapshots(keep_count=10)
                except Exception as e:
                    logger.error(f"Failed to create snapshot at height {block.header.height}: {e}")

        logger.info(f"Block {self.height} added. Hash: {self.last_hash[:8]}... (Round {round})")
        return True

    def _distribute_rewards(self, block: Block, state: AccountState):
        """
        Distributes block reward and transaction fees according to economic model.

        Economic Model (Phase 1.2):
        - Block reward: split 70% validators, 30% miners (from ECONOMIC_CONFIG)
        - Transaction fees: 90% validator, 10% treasury
        - Dust from integer division: burned
        - Minting/burning tracked in state
        """
        from protocol.config.economic_model import ECONOMIC_CONFIG, TREASURY_ADDRESS

        proposer_addr = block.header.proposer_address
        val = state.get_validator(proposer_addr)

        if not val or not val.is_active:
            return

        # Determine validator reward address
        target_addr = val.reward_address
        if not target_addr:
            try:
                target_addr = address_from_pubkey(bytes.fromhex(val.pq_pub_key), prefix=self.config.bech32_prefix_acc)
            except:
                logger.warning(f"Could not determine reward address for {proposer_addr}")
                return

        # ═══════════════════════════════════════════════════════════════
        # 1. Calculate block reward and split into pools
        # ═══════════════════════════════════════════════════════════════
        block_reward = calculate_block_reward(block.header.height)

        # Mint new tokens (block reward)
        state.mint_tokens(block_reward, reason="block_reward")

        # Split reward into validator and miner pools
        reward_split = ECONOMIC_CONFIG.distribute_block_reward(block_reward)
        validator_pool = reward_split['validator_pool']
        miner_pool = reward_split['miner_pool']

        # ═══════════════════════════════════════════════════════════════
        # 2. Calculate and distribute transaction fees
        # ═══════════════════════════════════════════════════════════════
        fees_total = 0
        for tx in block.txs:
            base_gas = GAS_PER_TYPE.get(tx.tx_type, 0)
            fees_total += base_gas * tx.gas_price

        # Split fees
        fee_split = ECONOMIC_CONFIG.distribute_fees(fees_total)
        validator_fee_share = fee_split['validator_share']
        treasury_fee_share = fee_split['treasury']
        fee_dust = fee_split['dust']

        # Send fees to treasury
        if treasury_fee_share > 0:
            treasury_acc = state.get_account(TREASURY_ADDRESS)
            treasury_acc.balance += treasury_fee_share
            state.set_account(treasury_acc)

        # Burn fee dust if any
        if fee_dust > 0:
            state.burn_tokens(fee_dust, reason="fee_dust")

        # ═══════════════════════════════════════════════════════════════
        # 3. Distribute validator pool to block producer
        # ═══════════════════════════════════════════════════════════════
        validator_total_reward = validator_pool + validator_fee_share

        acc = state.get_account(target_addr)

        if val.total_delegated > 0:
            # Validator has delegations - apply commission
            commission_amount = int(validator_total_reward * val.commission_rate)
            delegators_share = validator_total_reward - commission_amount

            # Validator gets commission
            acc.balance += commission_amount

            # Distribute to delegators (handles dust burning internally)
            dust = self._distribute_delegator_rewards(state, val, delegators_share, state.epoch_index)
            if dust > 0:
                state.burn_tokens(dust, reason="delegator_reward_dust")

            logger.info(
                f"Block {block.header.height}: Validator {target_addr[:12]}... "
                f"commission={commission_amount}, delegators={delegators_share-dust}, "
                f"dust_burned={dust}"
            )
        else:
            # No delegations - validator gets everything
            acc.balance += validator_total_reward

        state.set_account(acc)

        # ═══════════════════════════════════════════════════════════════
        # 4. Distribute miner pool (TODO: Phase 2A - PoC implementation)
        # ═══════════════════════════════════════════════════════════════
        # For now, if no miners in block → burn miner pool
        # In Phase 2A, this will call miner_reward_distributor.distribute_miner_rewards()
        if miner_pool > 0:
            # TODO: Extract miner submissions from block txs
            # miner_submissions = self._extract_miner_submissions(block)
            # distributed, dust = miner_reward_distributor.distribute_miner_rewards(miner_pool, miner_submissions, state)
            # state.burn_tokens(dust, reason="miner_reward_dust")

            # STUB: Burn miner pool until Phase 2A
            state.burn_tokens(miner_pool, reason="miner_pool_unused")
            logger.debug(f"Miner pool {miner_pool} burned (no PoC workers yet)")

    def _distribute_delegator_rewards(self, state: AccountState, validator: Validator, delegators_share: int, epoch: int) -> int:
        """
        Distributes delegators_share proportionally to all delegators.
        Records rewards in each delegator's reward_history.

        Args:
            state: Current account state
            validator: Validator whose delegators receive rewards
            delegators_share: Total amount to distribute
            epoch: Current epoch for reward tracking

        Returns:
            dust: Undistributed remainder from integer division (to be burned)
        """
        if not validator.delegations:
            logger.warning(f"Validator {validator.address} has total_delegated={validator.total_delegated} but no delegation records")
            return delegators_share  # All becomes dust

        total_delegated = validator.total_delegated
        if total_delegated == 0:
            logger.warning(f"Validator {validator.address} has delegations but total_delegated=0")
            return delegators_share  # All becomes dust

        # Distribute proportionally to each delegator
        distributed_total = 0
        for delegation in validator.delegations:
            # Calculate proportional share
            delegator_reward = (delegators_share * delegation.amount) // total_delegated

            if delegator_reward > 0:
                # Get delegator account and add reward
                delegator_acc = state.get_account(delegation.delegator)
                delegator_acc.balance += delegator_reward

                # Track reward in history
                if epoch not in delegator_acc.reward_history:
                    delegator_acc.reward_history[epoch] = 0
                delegator_acc.reward_history[epoch] += delegator_reward

                state.set_account(delegator_acc)
                distributed_total += delegator_reward

        # Calculate dust (remainder from integer division)
        dust = delegators_share - distributed_total

        # Log distribution
        logger.debug(
            f"Distributed {distributed_total} to {len(validator.delegations)} delegators "
            f"of validator {validator.address}, dust={dust}"
        )

        return dust

    def compute_poc_root(self, txs: List[Transaction]) -> str:
        leaves = []
        for tx in txs:
            if tx.tx_type == TxType.SUBMIT_RESULT:
                try:
                    res = ComputeResult(**tx.payload)
                    # Hash the result content
                    data = res.model_dump_json().encode("utf-8")
                    leaves.append(sha256(data))
                except Exception:
                    pass 

        if not leaves:
            return ""

        return self.state._compute_merkle_root_from_leaves(leaves).hex()

    def get_block(self, height: int) -> Optional[Block]:
        data = self.db.get_block_by_height(height)
        if data:
            return Block.model_validate_json(data)
        return None

    def _rebuild_state_from_blocks_impl(self):
        """
        Полностью пересчитывает state из блоков.
        Используется для восстановления / валидации БД.
        """
        logger.info("Rebuilding state from blocks...")
        
        # 1. Clear state tables
        self.db.clear_state()
        self.state = AccountState.empty(self.db)
        self.height = -1
        self.last_hash = "0" * 64
        self.last_block_timestamp = 0
        
        # 2. Re-apply genesis allocation
        self._apply_genesis_allocation()
        self._apply_genesis_validators()
        
        # 3. Replay blocks
        last = self.db.get_last_block()
        current_height = last[0] if last else -1
        
        for h in range(0, current_height + 1):
            block = self.get_block(h)
            if not block:
                logger.error(f"Missing block {h} during rebuild")
                raise ValueError(f"Missing block {h}")

            # Apply transactions
            for tx in block.txs:
                self.state.apply_transaction(tx, current_height=block.header.height)

            # Check state_root BEFORE any post-TX operations (matches proposer/validator flow)
            actual_root = self.state.compute_state_root()
            if block.header.state_root and block.header.state_root != actual_root:
                 logger.warning(f"State root mismatch at {h}: expected {block.header.state_root}, got {actual_root}")

            # Epoch Logic Replay (AFTER state_root check)
            if (h + 1) % self.config.epoch_length_blocks == 0:
                 self._process_epoch_transition(self.state)

            # Distribute rewards and process unbondings (match add_block flow)
            self._distribute_rewards(block, self.state)
            self.state.process_unbonding_queue(block.header.height)
            self._track_proposer_performance(block)
            self._track_missed_blocks(block)

            # Check PoC root
            expected_poc_root = self.compute_poc_root(block.txs)
            if block.header.compute_root and block.header.compute_root != expected_poc_root:
                 logger.warning(f"PoC root mismatch at {h}: expected {block.header.compute_root}, got {expected_poc_root}")

            # Update consensus and chain tips
            if (h + 1) % self.config.epoch_length_blocks == 0:
                self._update_consensus_from_state()
            self.height = block.header.height
            self.last_hash = block.hash()
            self.last_block_timestamp = block.header.timestamp
        
        # 4. Save final state
        self.state.persist()
        # Update consensus
        self._update_consensus_from_state()
        logger.info("State rebuild complete.")

    def _process_epoch_transition(self, state: AccountState):
        """
        Process epoch changes with performance-based validator selection (Phase 0).
        Jails validators who missed too many blocks, calculates performance scores,
        and selects top N validators by score (not just stake).
        """
        all_vals = state.get_all_validators()
        current_height = self.height + 1

        logger.info(f"=== Epoch {state.epoch_index} Transition (Block {current_height}) ===")

        # 0. Reset inactive validators' stats BEFORE filtering (recovery mechanism)
        # This allows validators who were deactivated to rejoin with a clean slate
        for v in all_vals:
            if not v.is_active:
                v.blocks_expected = 0
                v.blocks_proposed = 0
                v.uptime_score = 1.0  # Fresh start
                state.set_validator(v)
                logger.debug(f"  Reset inactive validator {v.address[:12]} for potential rejoin")

        # 1. Filter candidates: sufficient stake and NOT jailed
        candidates = [
            v for v in all_vals
            if v.power >= self.config.min_validator_stake
            and v.jailed_until_height < current_height
        ]

        # 2. Filter by minimum uptime score (if they have history)
        candidates = [
            v for v in candidates
            if v.blocks_expected == 0 or v.uptime_score >= self.config.min_uptime_score
        ]

        # 3. Calculate performance scores for all candidates
        for v in candidates:
            old_score = v.performance_score
            v.performance_score = self._calculate_performance_score(v, state)
            v.uptime_score = v.blocks_proposed / max(v.blocks_expected, 1) if v.blocks_expected > 0 else 1.0
            logger.info(f"  Validator {v.address[:12]}: score={v.performance_score:.3f} (was {old_score:.3f}), uptime={v.uptime_score:.3f}, proposed={v.blocks_proposed}/{v.blocks_expected}, missed={v.missed_blocks}")
            state.set_validator(v)

        # 4. Sort by performance_score (not just power!)
        candidates.sort(key=lambda v: v.performance_score, reverse=True)

        # 5. Select top N
        new_active = candidates[:self.config.max_validators]
        active_addresses = {v.address for v in new_active}

        # 6. Apply penalties & jail for those who violated rules
        for v in all_vals:
            # Check for jail condition (missed too many blocks)
            if v.missed_blocks >= self.config.max_missed_blocks_sequential and v.is_active:
                self._jail_validator(v, state, current_height)
                continue  # Skip further processing for this validator

            # Update active status
            was_active = v.is_active
            is_active = v.address in active_addresses

            if was_active != is_active:
                v.is_active = is_active
                if not is_active:
                    logger.warning(f"  ❌ Validator {v.address[:12]} removed from active set (low performance)")
                else:
                    logger.info(f"  ✅ Validator {v.address[:12]} added to active set")
                state.set_validator(v)

        # 7. Log new active set
        active_vals = [v for v in state.get_all_validators() if v.is_active]
        logger.info(f"New Active Set ({len(active_vals)}/{self.config.max_validators}):")
        for v in sorted(active_vals, key=lambda x: x.performance_score, reverse=True):
            logger.info(f"  - {v.address[:12]} | score={v.performance_score:.3f} | power={v.power}")

        # 8. Increment epoch
        state.epoch_index += 1

        # 9. Start tracking for the new epoch
        self._start_epoch_tracking(state)

    # ========================================
    # Phase 0: Validator Performance & Slashing
    # ========================================

    def _track_proposer_performance(self, block: Block):
        """
        Tracks the proposer's performance when a block is added.
        Updates blocks_proposed, last_block_height, and resets missed_blocks.
        """
        proposer_addr = block.header.proposer_address
        proposer_val = self.state.get_validator(proposer_addr)

        if proposer_val:
            proposer_val.blocks_proposed += 1
            proposer_val.last_block_height = block.header.height
            proposer_val.last_seen_height = block.header.height
            proposer_val.missed_blocks = 0  # Reset consecutive misses
            self.state.set_validator(proposer_val)
            logger.debug(f"Validator {proposer_addr[:12]} proposed block {block.header.height}")

    def _track_missed_blocks(self, block: Block):
        """
        Checks if there were missed blocks between last_block and current block
        based on timestamps. Increments missed_blocks for validators who should
        have proposed but didn't.
        """
        if self.height < 0:
            return  # Genesis block

        time_diff = block.header.timestamp - self.last_block_timestamp
        block_time = self.config.block_time_sec

        # Calculate how many blocks should have been created
        expected_blocks = time_diff // block_time

        if expected_blocks > 1:
            # There were missed blocks!
            missed_count = int(expected_blocks - 1)
            logger.warning(f"Detected {missed_count} missed blocks (time gap: {time_diff}s)")

            for i in range(1, missed_count + 1):
                missed_height = self.height + i
                expected_proposer = self.consensus.get_proposer(missed_height, round=0)

                if expected_proposer:
                    val = self.state.get_validator(expected_proposer.address)
                    if val and val.is_active:
                        val.missed_blocks += 1
                        logger.warning(f"⚠️  Validator {val.address[:12]} missed block at height {missed_height} (total consecutive: {val.missed_blocks})")
                        self.state.set_validator(val)

    def _calculate_performance_score(self, val: Validator, state: AccountState) -> float:
        """
        Calculates performance score for a validator.

        Formula:
        - 60% uptime (blocks_proposed / blocks_expected)
        - 20% stake ratio (relative to total network stake)
        - 20% penalty history (1 - penalty_ratio)
        """
        # Uptime score
        if val.blocks_expected > 0:
            uptime_score = val.blocks_proposed / val.blocks_expected
        else:
            uptime_score = 1.0  # No expectations yet

        # Stake ratio (relative to total network stake)
        all_vals = state.get_all_validators()
        total_stake = sum(v.power for v in all_vals)
        stake_ratio = val.power / max(total_stake, 1)

        # Penalty ratio (capped at 0.5)
        penalty_ratio = min(val.total_penalties / max(val.power, 1), 0.5)

        # Combined score
        score = (
            0.6 * uptime_score +
            0.2 * stake_ratio +
            0.2 * (1 - penalty_ratio)
        )

        return max(0.0, min(1.0, score))  # Clamp to [0, 1]

    def _jail_validator(self, val: Validator, state: AccountState, current_height: int):
        """
        Jails a validator for missing too many blocks.
        Applies graduated penalty (slashing) based on jail count:
        - 1st jail: 5% (base rate)
        - 2nd jail: 10% (double)
        - 3rd+ jail: 100% (ejection)
        """
        # Phase 3: Graduated slashing based on jail count
        base_rate = self.config.slashing_penalty_rate  # 0.05 (5%)

        if val.jail_count == 0:
            # First offense: base rate
            penalty_rate = base_rate
        elif val.jail_count == 1:
            # Second offense: double
            penalty_rate = base_rate * 2
        else:
            # Third+ offense: full slash (ejection)
            penalty_rate = 1.0

        # Calculate penalty (% of stake)
        penalty = int(val.power * penalty_rate)

        # Apply penalty
        val.power = max(0, val.power - penalty)
        val.total_penalties += penalty
        val.jail_count += 1
        val.jailed_until_height = current_height + self.config.jail_duration_blocks
        val.missed_blocks = 0  # Reset counter
        val.is_active = False

        logger.warning(
            f"⚠️  JAILED: Validator {val.address[:12]} | "
            f"Penalty: {penalty} | "
            f"Jail #{val.jail_count} until block {val.jailed_until_height} | "
            f"Remaining power: {val.power}"
        )

        # If too many jails -> permanent ejection
        if val.jail_count >= self.config.ejection_threshold_jails:
            logger.error(f"❌ EJECTED: Validator {val.address[:12]} (too many jails: {val.jail_count})")
            val.is_active = False
            val.power = 0  # Full slash

        state.set_validator(val)

    def _start_epoch_tracking(self, state: AccountState):
        """
        Initializes expected_blocks counter for validators at epoch start.
        - Active validators: set blocks_expected based on round-robin distribution
        - Inactive validators: reset blocks_expected to 0 (clean slate for rejoin)
        """
        all_vals = state.get_all_validators()
        active_vals = [v for v in all_vals if v.is_active]
        blocks_per_epoch = self.config.epoch_length_blocks

        # Reset stats for ALL validators first (allows inactive ones to rejoin)
        for v in all_vals:
            if not v.is_active:
                # Reset inactive validators - gives them clean slate for next epoch filter
                # (filter passes if blocks_expected == 0)
                v.blocks_expected = 0
                v.blocks_proposed = 0
                state.set_validator(v)
                logger.debug(f"Epoch tracking: {v.address[:12]} (inactive) reset for potential rejoin")

        if not active_vals:
            return

        # In Round-Robin, each validator should create roughly equal blocks
        expected_per_val = blocks_per_epoch // len(active_vals)
        remainder = blocks_per_epoch % len(active_vals)

        for i, v in enumerate(sorted(active_vals, key=lambda x: x.address)):
            v.blocks_expected = expected_per_val + (1 if i < remainder else 0)
            v.blocks_proposed = 0  # Reset for new epoch
            state.set_validator(v)
            logger.debug(f"Epoch tracking: {v.address[:12]} expected to propose {v.blocks_expected} blocks")

    def _rollback_last_block_impl(self):
        """
        Deletes the last block and rebuilds state up to the new last block.
        Used for fork resolution.
        """
        if self.height <= 0:
            logger.warning("Cannot rollback genesis block or empty chain.")
            return
        
        logger.info(f"Rolling back block {self.height}...")
        self.db.delete_block(self.height)
        
        # Reload chain state to reflect new height and hash
        self._load_chain_state()
        
        # Rebuild state from blocks to ensure consistency after rollback
        self.rebuild_state_from_blocks()
        
        logger.info(f"Chain rolled back to height {self.height}.")

    def _rollback_to_height_impl(self, target_height: int):
        """
        Roll back chain to a specific height (inclusive).
        Deletes blocks above target_height and rebuilds state.
        """
        if target_height < -1:
            raise ValueError("target_height must be >= -1")
        if self.height <= target_height:
            return

        logger.warning(f"Rolling back chain from height {self.height} to {target_height}...")
        for h in range(self.height, target_height, -1):
            self.db.delete_block(h)

        self._load_chain_state()
        self._rebuild_state_from_blocks_impl()
        logger.info(f"Chain rollback complete. Current height: {self.height}")
