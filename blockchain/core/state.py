from typing import Dict, Optional, List
import json
import threading
from .accounts import Account
from ...protocol.types.tx import Transaction
from ...protocol.types.common import TxType
from ...protocol.types.validator import Validator, Delegation
from ...protocol.types.poc import ComputeResult
from ...protocol.crypto.hash import sha256, sha256_hex
from ...protocol.crypto.addresses import address_from_pubkey
from ...protocol.crypto.keys import verify
from ...protocol.config.params import GAS_PER_TYPE, CURRENT_NETWORK
from ..storage.db import StorageDB

class AccountState:
    def __init__(self, db: StorageDB, accounts: Dict[str, Account] = None, validators: Dict[str, Validator] = None):
        self.db = db
        # Cache for modified/accessed accounts: address -> Account
        self._accounts: Dict[str, Account] = accounts if accounts is not None else {}
        # Cache for validators: address -> Validator
        self._validators: Dict[str, Validator] = validators if validators is not None else {}
        
        # Epoch info (in memory for now, should be persisted)
        self.epoch_index = 0

    def clone(self) -> 'AccountState':
        """Creates a copy of the state (for simulation)."""
        # Deep copy accounts in cache
        new_accounts = {k: v.model_copy() for k, v in self._accounts.items()}
        new_validators = {k: v.model_copy() for k, v in self._validators.items()}
        cloned = AccountState(self.db, new_accounts, new_validators)
        cloned.epoch_index = self.epoch_index
        return cloned

    def get_account(self, address: str) -> Account:
        if address in self._accounts:
            return self._accounts[address]
        
        # Try load from DB
        raw_json = self.db.get_state(f"acc:{address}")
        if raw_json:
            acc = Account.model_validate_json(raw_json)
            self._accounts[address] = acc
            return acc
            
        # Return generic new account
        return Account(address=address)

    def set_account(self, account: Account):
        """Updates account in local cache."""
        self._accounts[account.address] = account

    def get_validator(self, address: str) -> Optional[Validator]:
        if address in self._validators:
            return self._validators[address]
        
        # Try load from DB
        raw_json = self.db.get_state(f"val:{address}")
        if raw_json:
            val = Validator.model_validate_json(raw_json)
            self._validators[address] = val
            return val
        return None

    def set_validator(self, validator: Validator):
        self._validators[validator.address] = validator

    def get_all_validators(self) -> List[Validator]:
        """Loads all validators from DB + cache overlay."""
        # Load all from DB
        all_db_data = self.db.get_state_by_prefix("val:")
        final_validators = {}
        
        for k, v in all_db_data.items():
            addr = k.split(":")[1]
            final_validators[addr] = Validator.model_validate_json(v)
            
        # Overlay cache
        for addr, val in self._validators.items():
            final_validators[addr] = val
            
        return list(final_validators.values())

    def persist(self):
        """Writes modified accounts and validators to DB."""
        for addr, acc in self._accounts.items():
            self.db.set_state(f"acc:{addr}", acc.model_dump_json())
        for addr, val in self._validators.items():
            self.db.set_state(f"val:{addr}", val.model_dump_json())
        
        self.db.set_state("epoch_index", str(self.epoch_index))

    def load_epoch_info(self):
        val = self.db.get_state("epoch_index")
        if val:
            self.epoch_index = int(val)

    def apply_transaction(self, tx: Transaction, current_height: Optional[int] = None) -> bool:
        """
        Applies transaction to state (in-memory). Raises error on failure.

        Args:
            tx: Transaction to apply
            current_height: Current block height (used for delegation tracking, etc.)
        """
        
        # 0. Crypto Verification
        if not tx.signature or not tx.pub_key:
             raise ValueError("Missing signature or pub_key")

        # Verify pub_key matches from_address
        # Determine prefix from address (part before '1')
        try:
            prefix = tx.from_address.split("1")[0]
            derived_addr = address_from_pubkey(bytes.fromhex(tx.pub_key), prefix=prefix)
            if derived_addr != tx.from_address:
                raise ValueError(f"pub_key mismatch: derived {derived_addr}, expected {tx.from_address}")
        except Exception as e:
             raise ValueError(f"Invalid address format or key: {e}")

        # Verify signature
        try:
            msg_hash_bytes = bytes.fromhex(tx.hash())
            sig_bytes = bytes.fromhex(tx.signature)
            pub_bytes = bytes.fromhex(tx.pub_key)
            
            if not verify(msg_hash_bytes, sig_bytes, pub_bytes):
                 raise ValueError("Invalid signature")
        except Exception as e:
             raise ValueError(f"Signature verification failed: {e}")

        sender = self.get_account(tx.from_address)
        
        # 1. Nonce check
        if tx.nonce != sender.nonce:
            raise ValueError(f"Invalid nonce: expected {sender.nonce}, got {tx.nonce}")
        
        # 2. Gas & Fee Calculation (New Logic)
        base_gas = GAS_PER_TYPE.get(tx.tx_type, 0)
        
        if tx.gas_limit < base_gas:
            raise ValueError(f"gas_limit {tx.gas_limit} too low for {tx.tx_type} (need {base_gas})")
        
        if tx.gas_price < CURRENT_NETWORK.min_gas_price:
             raise ValueError(f"gas_price {tx.gas_price} below minimum {CURRENT_NETWORK.min_gas_price}")

        needed_fee = base_gas * tx.gas_price
        if tx.fee < needed_fee:
            raise ValueError(f"fee {tx.fee} too low (need {needed_fee})")

        # We deduct exactly needed_fee (burned/collected), rest of tx.fee is ignored (savings)
        spent_fee = needed_fee

        # For UNSTAKE and UPDATE_VALIDATOR, we only need fee (no amount transfer)
        # For UNDELEGATE, amount is returned from validator delegation
        # For other types, we need amount + fee
        if tx.tx_type in [TxType.UNSTAKE, TxType.UPDATE_VALIDATOR]:
            total_cost = spent_fee
        elif tx.tx_type == TxType.UNDELEGATE:
            # UNDELEGATE only requires fee, amount is returned from delegation
            total_cost = spent_fee
        else:
            total_cost = tx.amount + spent_fee

        if sender.balance < total_cost:
            raise ValueError(f"Insufficient balance: have {sender.balance}, need {total_cost}")

        # 3. Update sender
        sender.balance -= total_cost
        sender.nonce += 1
        self.set_account(sender)
        
        # 4. Route by Type
        if tx.tx_type == TxType.TRANSFER:
            if not tx.to_address:
                raise ValueError("Transfer must have to_address")
            recipient = self.get_account(tx.to_address)
            recipient.balance += tx.amount
            self.set_account(recipient)
            
        elif tx.tx_type == TxType.STAKE:
            # 1. Derive Consensus Address from PubKey (if creating new)
            # We use 'cpcvalcons' prefix for validators
            
            # For MVP: We assume if user wants to stake, they provide pub_key in payload
            # to calculate consensus address. Or we use the account address as operator address?
            # Correct way: Validator is identified by consensus address.
            # But we need to map Owner(cpc) -> Validator(cpcvalcons).
            
            # Current simplified logic:
            # If pub_key provided: Create new validator with Derived Address.
            # If pub_key NOT provided: Try to find validator by... sender address?
            #   But sender address is 'cpc...', validator is 'cpcvalcons...'. They are DIFFERENT strings.
            #   We need a mapping or just ALWAYS require pub_key to derive address.
            #   Or just allow update by sender address if we stored map.
            
            # Let's require pub_key for now or try to derive if we knew it. 
            # But we don't know pub_key of sender unless provided.
            
            pub_key_hex = tx.payload.get("pub_key")
            
            if pub_key_hex:
                # Create/Update based on consensus address
                val_pub_bytes = bytes.fromhex(pub_key_hex)
                val_addr = address_from_pubkey(val_pub_bytes, prefix="cpcvalcons")
                
                val = self.get_validator(val_addr)
                if not val:
                    # New
                    val = Validator(
                        address=val_addr,
                        pq_pub_key=pub_key_hex, # Updated field
                        power=tx.amount,
                        is_active=False,
                        reward_address=tx.from_address # Default reward address to sender
                    )
                else:
                    # Add stake
                    val.power += tx.amount
                
                self.set_validator(val)
            else:
                # If no pub_key, maybe user wants to delegate? 
                # For now, MVP requires pub_key to identify validator.
                raise ValueError("STAKE transaction must provide 'pub_key' in payload")

        elif tx.tx_type == TxType.UNSTAKE:
            # UNSTAKE: Withdraw stake from validator
            # User must provide pub_key in payload to identify validator
            pub_key_hex = tx.payload.get("pub_key")

            if not pub_key_hex:
                raise ValueError("UNSTAKE transaction must provide 'pub_key' in payload")

            # Derive validator address from pub_key
            val_pub_bytes = bytes.fromhex(pub_key_hex)
            val_addr = address_from_pubkey(val_pub_bytes, prefix="cpcvalcons")

            # Get validator
            val = self.get_validator(val_addr)
            if not val:
                raise ValueError(f"Validator {val_addr} not found")

            # Check if validator has enough stake
            if val.power < tx.amount:
                raise ValueError(f"Insufficient stake: validator has {val.power}, trying to unstake {tx.amount}")

            # Apply slashing penalty if validator is jailed
            penalty_amount = 0
            if val.jailed_until_height > 0:
                # Validator is jailed - apply penalty (e.g., 10% of unstake amount)
                penalty_rate = 0.10  # 10% penalty for unstaking while jailed
                penalty_amount = int(tx.amount * penalty_rate)

            # Calculate actual amount to return (after penalty)
            return_amount = tx.amount - penalty_amount

            # Decrease validator power
            val.power -= tx.amount

            # Deactivate validator if power reaches zero
            if val.power == 0:
                val.is_active = False

            self.set_validator(val)

            # Return tokens to sender (minus penalty)
            sender = self.get_account(tx.from_address)
            sender.balance += return_amount
            self.set_account(sender)

            # Penalty is burned (not returned to anyone)

        elif tx.tx_type == TxType.SUBMIT_RESULT:
             # S4.3: Validate PoC Result structure
             try:
                 res = ComputeResult(**tx.payload)
                 if res.worker_address != tx.from_address:
                     raise ValueError(f"Worker address mismatch: payload {res.worker_address} vs tx {tx.from_address}")

                 # Here we would verify the Proof (ZK / Hash)
                 # For MVP, we accept it if structure is valid.
             except Exception as e:
                 raise ValueError(f"Invalid ComputeResult: {e}")

        elif tx.tx_type == TxType.UPDATE_VALIDATOR:
            # Phase 1: Update validator metadata (name, website, description)
            pub_key_hex = tx.payload.get("pub_key")
            if not pub_key_hex:
                raise ValueError("UPDATE_VALIDATOR must provide 'pub_key' in payload")

            # Derive validator address
            val_pub_bytes = bytes.fromhex(pub_key_hex)
            val_addr = address_from_pubkey(val_pub_bytes, prefix="cpcvalcons")

            # Get validator
            val = self.get_validator(val_addr)
            if not val:
                raise ValueError(f"Validator {val_addr} not found")

            # Only validator owner can update metadata
            if val.reward_address != tx.from_address:
                raise ValueError(f"Only validator owner can update metadata")

            # Update metadata fields
            if "name" in tx.payload:
                name = tx.payload["name"]
                if len(name) > 64:
                    raise ValueError("Validator name too long (max 64 chars)")
                val.name = name

            if "website" in tx.payload:
                website = tx.payload["website"]
                if len(website) > 128:
                    raise ValueError("Website URL too long (max 128 chars)")
                val.website = website

            if "description" in tx.payload:
                description = tx.payload["description"]
                if len(description) > 256:
                    raise ValueError("Description too long (max 256 chars)")
                val.description = description

            if "commission_rate" in tx.payload:
                commission_rate = float(tx.payload["commission_rate"])
                if commission_rate < 0 or commission_rate > 1.0:
                    raise ValueError("Commission rate must be between 0.0 and 1.0")
                val.commission_rate = commission_rate

            self.set_validator(val)

        elif tx.tx_type == TxType.DELEGATE:
            # Phase 2: Delegate tokens to a validator
            validator_addr = tx.payload.get("validator")
            if not validator_addr:
                raise ValueError("DELEGATE must provide 'validator' address in payload")

            # Get validator
            val = self.get_validator(validator_addr)
            if not val:
                raise ValueError(f"Validator {validator_addr} not found")

            # Check minimum delegation amount
            min_delegation = CURRENT_NETWORK.min_delegation
            if tx.amount < min_delegation:
                raise ValueError(f"Delegation amount {tx.amount} below minimum {min_delegation} ({min_delegation / 10**18} CPC)")

            # Update validator's delegated amount
            val.total_delegated += tx.amount
            val.power += tx.amount  # Delegated stake counts as voting power

            # Track individual delegation
            # Check if delegator already has delegation to this validator
            existing_delegation = next(
                (d for d in val.delegations if d.delegator == tx.from_address),
                None
            )

            if existing_delegation:
                # Update existing delegation
                existing_delegation.amount += tx.amount
            else:
                # Create new delegation record
                new_delegation = Delegation(
                    delegator=tx.from_address,
                    validator=validator_addr,
                    amount=tx.amount,
                    created_height=current_height if current_height is not None else 0
                )
                val.delegations.append(new_delegation)

            self.set_validator(val)

        elif tx.tx_type == TxType.UNDELEGATE:
            # Phase 2: Undelegate tokens from a validator
            validator_addr = tx.payload.get("validator")
            if not validator_addr:
                raise ValueError("UNDELEGATE must provide 'validator' address in payload")

            # Get validator
            val = self.get_validator(validator_addr)
            if not val:
                raise ValueError(f"Validator {validator_addr} not found")

            # Find delegator's delegation
            delegator_delegation = next(
                (d for d in val.delegations if d.delegator == tx.from_address),
                None
            )

            if not delegator_delegation:
                raise ValueError(f"No delegation found from {tx.from_address} to {validator_addr}")

            # Check if delegator has enough delegated amount
            if delegator_delegation.amount < tx.amount:
                raise ValueError(f"Insufficient delegation: have {delegator_delegation.amount}, trying to undelegate {tx.amount}")

            # Update delegation record
            delegator_delegation.amount -= tx.amount

            # Remove delegation if amount becomes zero
            if delegator_delegation.amount == 0:
                val.delegations.remove(delegator_delegation)

            # Update validator's total delegated amount
            val.total_delegated -= tx.amount
            val.power -= tx.amount

            # Return tokens to delegator
            # TODO: Implement unbonding period (21 days) in next step
            sender = self.get_account(tx.from_address)
            sender.balance += tx.amount
            self.set_account(sender)

            self.set_validator(val)

        elif tx.tx_type == TxType.UNJAIL:
            # Phase 3: Request early release from jail (expensive!)
            pub_key_hex = tx.payload.get("pub_key")
            if not pub_key_hex:
                raise ValueError("UNJAIL must provide 'pub_key' in payload")

            # Derive validator address
            val_pub_bytes = bytes.fromhex(pub_key_hex)
            val_addr = address_from_pubkey(val_pub_bytes, prefix="cpcvalcons")

            # Get validator
            val = self.get_validator(val_addr)
            if not val:
                raise ValueError(f"Validator {val_addr} not found")

            # Check if validator is jailed
            if val.jailed_until_height == 0:
                raise ValueError(f"Validator {val_addr} is not jailed")

            # Only validator owner can unjail
            if val.reward_address != tx.from_address:
                raise ValueError("Only validator owner can unjail")

            # Check if validator paid unjail fee (in tx.amount)
            # TODO: Use self.config.unjail_fee when available
            unjail_fee = 1000 * 10**18  # 1000 CPC
            if tx.amount < unjail_fee:
                raise ValueError(f"Insufficient unjail fee: need {unjail_fee}, got {tx.amount}")

            # Release from jail
            val.jailed_until_height = 0
            val.missed_blocks = 0
            val.is_active = True  # Reactivate validator

            self.set_validator(val)

            # Unjail fee is burned (already deducted from balance)

        # 5. Handle Fees - implicitly burned or collected by block proposer later
        return True

    def compute_state_root(self) -> str:
        """Computes Merkle root of the entire account state."""
        # 1. Load ALL accounts from DB (expensive but necessary for MVP correctness)
        all_db_data = self.db.get_state_by_prefix("acc:")
        
        final_state: Dict[str, Account] = {}
        
        # Parse DB state
        for k, v in all_db_data.items():
            addr = k.split(":")[1]
            final_state[addr] = Account.model_validate_json(v)
            
        # 2. Overlay local cache (latest changes)
        for addr, acc in self._accounts.items():
            final_state[addr] = acc
            
        # 3. Sort and build leaves
        items = []
        for addr in sorted(final_state.keys()):
            acc = final_state[addr]
            # Leaf data: address + balance + nonce
            leaf_data = (
                addr
                + str(acc.balance)
                + str(acc.nonce)
            ).encode("utf-8")
            items.append(sha256(leaf_data))
            
        if not items:
            return sha256(b"").hex()
            
        # 4. Compute Merkle Root
        return self._compute_merkle_root_from_leaves(items).hex()

    def _compute_merkle_root_from_leaves(self, leaves: List[bytes]) -> bytes:
        if not leaves:
            return b'\x00' * 32
        if len(leaves) == 1:
            return leaves[0]
            
        # Ensure even number of leaves
        if len(leaves) % 2 == 1:
            leaves.append(leaves[-1])
            
        new_level = []
        for i in range(0, len(leaves), 2):
            new_level.append(sha256(leaves[i] + leaves[i+1]))
            
        return self._compute_merkle_root_from_leaves(new_level)

    @staticmethod
    def empty(db: StorageDB) -> 'AccountState':
        """Returns an empty state."""
        return AccountState(db, {})
