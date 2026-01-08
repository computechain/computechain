#!/usr/bin/env python3
"""
Phase 1.4 - Transaction Generator
Генерирует транзакционную нагрузку для stress testing
"""

import argparse
import time
import random
import requests
import json
import logging
import traceback
import threading
from datetime import datetime, timedelta
from typing import List, Dict
import sys
import os

# Add parent directory to path - detect if running from inside computechain/ or parent
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(script_dir, '../..'))
repo_name = os.path.basename(repo_root)

if repo_name == "computechain":
    # Running from inside computechain/ - add parent to path
    parent_dir = os.path.dirname(repo_root)
    sys.path.insert(0, parent_dir)
else:
    # Running from parent directory
    sys.path.insert(0, repo_root)

from computechain.cli.keystore import KeyStore
from computechain.protocol.types.tx import Transaction, TxType
from computechain.protocol.crypto.keys import sign, public_key_from_private
from computechain.protocol.crypto.hash import sha256
from computechain.protocol.config.params import DECIMALS
from computechain.scripts.testing.nonce_manager import NonceManager
# Phase 1.4.1: SSE dependency REMOVED - simplified testing approach

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/tx_generator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TxGenerator:
    """Transaction generator for load testing."""

    def __init__(self, node_url: str, mode: str = "low"):
        self.node_url = node_url
        self.mode = mode
        self.keystore = KeyStore()

        # Load configuration based on mode
        self.config = self._get_config(mode)

        # Statistics
        self.stats = {
            'total_sent': 0,
            'successful': 0,
            'failed': 0,
            'by_type': {},
            'start_time': datetime.now()
        }

        # Nonce Manager (Phase 1.4.1: Simplified - no SSE dependency)
        # Uses gap-filling algorithm with periodic blockchain sync
        self.nonce_manager = NonceManager(self._get_nonce)

        # Account-level locks to prevent race condition in nonce allocation
        # Phase 1.4.3: Each account gets its own lock to ensure only one thread
        # can generate TX for that account at a time
        self.account_locks = {}
        self.locks_lock = threading.Lock()  # Lock for managing account_locks dict

        # Set running flag BEFORE starting threads
        self.running = True

        # Phase 1.4.1: SSE removed - use simple periodic sync instead
        logger.info("Simple nonce management ENABLED (no SSE dependency)")

        # Generate test accounts
        self.test_accounts = self._generate_test_accounts(100)

        # Fund test accounts from faucet
        self._fund_test_accounts()

        # Start background thread for transaction tracking
        self.tracker_thread = threading.Thread(target=self._transaction_tracker, daemon=True)
        self.tracker_thread.start()

    def _get_config(self, mode: str) -> Dict:
        """Get configuration for specified mode."""
        configs = {
            'low': {
                'tps_min': 1,
                'tps_max': 5,
                'send_ratio': 0.80,
                'delegate_ratio': 0.15,
                'undelegate_ratio': 0.05,
                'amount_min': 1 * (10**DECIMALS),
                'amount_max': 100 * (10**DECIMALS),
            },
            'medium': {
                'tps_min': 10,
                'tps_max': 50,
                'send_ratio': 0.60,
                'delegate_ratio': 0.20,
                'undelegate_ratio': 0.10,
                'update_validator_ratio': 0.10,
                'amount_min': 10 * (10**DECIMALS),
                'amount_max': 1000 * (10**DECIMALS),
            },
            'high': {
                'tps_min': 100,
                'tps_max': 500,
                'send_ratio': 0.50,
                'delegate_ratio': 0.25,
                'undelegate_ratio': 0.15,
                'update_validator_ratio': 0.10,
                'amount_min': 1 * (10**DECIMALS),  # Reduced from 100 to prevent balance exhaustion
                'amount_max': 100 * (10**DECIMALS),  # Reduced from 10000 to prevent balance exhaustion
            }
        }
        return configs.get(mode, configs['low'])

    def _generate_test_accounts(self, count: int) -> List[Dict]:
        """Generate test accounts for transactions."""
        accounts = []

        # Create or load test accounts
        for i in range(count):
            key_name = f"test_account_{i}"
            try:
                key = self.keystore.get_key(key_name)
                if key is not None:
                    accounts.append(key)
                else:
                    # Create new account if doesn't exist
                    key = self.keystore.create_key(key_name)
                    accounts.append(key)
                    logger.debug(f"Created test account: {key_name}")
            except Exception as e:
                logger.warning(f"Failed to create {key_name}: {e}")

        logger.info(f"Generated {len(accounts)} test accounts")
        return accounts

    def _fund_test_accounts(self):
        """Fund test accounts from faucet."""
        logger.info("Funding test accounts from faucet...")

        # Load faucet account
        faucet = self.keystore.get_key('faucet')
        if not faucet:
            logger.error("Faucet account not found!")
            return

        # Fund in batches to speed up (send batch, then wait for block)
        batch_size = 10
        funded_count = 0

        for batch_start in range(0, len(self.test_accounts), batch_size):
            batch_end = min(batch_start + batch_size, len(self.test_accounts))
            batch = self.test_accounts[batch_start:batch_end]

            logger.info(f"Funding batch {batch_start//batch_size + 1} (accounts {batch_start+1}-{batch_end})...")

            batch_sent = 0
            for account in batch:
                # Check if account needs funding (must have at least 1M CPC)
                balance = self._get_balance(account['address'])
                min_balance = 1_000_000 * (10**DECIMALS)
                if balance >= min_balance:
                    logger.debug(f"Account {account['address'][:20]}... already funded")
                    funded_count += 1
                    continue

                try:
                    # Send 1,000,000 CPC to each account
                    amount = 1_000_000 * (10**DECIMALS)
                    nonce = self._get_nonce(faucet['address'])

                    tx = Transaction(
                        tx_type=TxType.TRANSFER,
                        from_address=faucet['address'],
                        to_address=account['address'],
                        amount=amount,
                        fee=21000000,
                        nonce=nonce,
                        gas_price=1000,
                        gas_limit=21000,
                        pub_key=faucet['public_key'],
                        signature=""
                    )

                    # Sign transaction
                    msg_hash = bytes.fromhex(tx.hash())
                    private_key = bytes.fromhex(faucet['private_key'])
                    signature = sign(msg_hash, private_key)
                    tx.signature = signature.hex()

                    # Broadcast
                    if self._broadcast_tx(tx):
                        funded_count += 1
                        batch_sent += 1
                        time.sleep(0.05)  # Small delay between txs in batch

                except Exception as e:
                    logger.warning(f"Failed to fund {account['address']}: {e}")

            logger.info(f"Batch sent: {batch_sent} transactions")

            # Wait for block to include this batch before sending next
            logger.info("Waiting 12s for batch to be included in block...")
            time.sleep(12)

        logger.info(f"Successfully funded {funded_count}/{len(self.test_accounts)} test accounts")

        # Wait a bit more to ensure all are confirmed
        logger.info("Waiting 10 more seconds for final confirmations...")
        time.sleep(10)

    def _get_balance(self, address: str) -> int:
        """Get current balance for address."""
        try:
            resp = requests.get(f"{self.node_url}/balance/{address}", timeout=5)
            if resp.status_code == 200:
                return int(resp.json().get('balance', 0))
            return 0
        except Exception as e:
            logger.debug(f"Failed to get balance for {address}: {e}")
            return 0

    def _get_nonce(self, address: str) -> int:
        """
        Get pending nonce for address from blockchain (Ethereum-style).

        Uses /nonce endpoint which returns pending nonce (includes pending TX).
        This eliminates need for complex client-side nonce tracking.
        """
        try:
            resp = requests.get(f"{self.node_url}/nonce/{address}", timeout=5)
            if resp.status_code == 200:
                return resp.json()['nonce']
            # Fallback to /balance if /nonce not available
            resp = requests.get(f"{self.node_url}/balance/{address}", timeout=5)
            if resp.status_code == 200:
                return resp.json()['nonce']
            return 0
        except Exception as e:
            logger.warning(f"Failed to get nonce for {address}: {e}")
            return 0

    def _transaction_tracker(self):
        """
        Background thread for tracking pending transactions (Phase 1.4.1: Simplified).

        - Checks for TX timeouts (marks stale TX as failed)
        - Periodic resync with blockchain to update nonces
        - No SSE dependency - relies on gap-filling algorithm
        """
        logger.info("Transaction tracker started (simplified mode)")

        while self.running:
            try:
                # Check for timed out pending transactions
                self.nonce_manager.check_timeouts()

                # Print nonce manager stats every 30 seconds
                if hasattr(self, '_last_stats_print'):
                    if time.time() - self._last_stats_print > 30:
                        stats = self.nonce_manager.get_stats()
                        logger.info(f"NonceManager stats: {stats}")
                        self._last_stats_print = time.time()
                else:
                    self._last_stats_print = time.time()

                # Sleep for 10 seconds before next check
                time.sleep(10)

            except Exception as e:
                logger.error(f"Error in transaction tracker: {e}")
                time.sleep(10)

        logger.info("Transaction tracker stopped")

    def _get_validators(self) -> List[Dict]:
        """Get list of validators."""
        try:
            resp = requests.get(f"{self.node_url}/validators", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('validators', [])
            return []
        except Exception as e:
            logger.warning(f"Failed to get validators: {e}")
            return []

    def _broadcast_tx(self, tx: Transaction) -> bool:
        """Broadcast transaction to node."""
        tx_hash = tx.hash()
        from_address = tx.from_address
        nonce = tx.nonce

        try:
            tx_json = tx.model_dump()
            tx_json['tx_type'] = tx.tx_type.value  # Serialize enum

            resp = requests.post(
                f"{self.node_url}/tx/send",
                json=tx_json,
                timeout=5
            )

            if resp.status_code == 200:
                # Check JSON response - server returns 200 even for rejected TX
                resp_json = resp.json()
                if resp_json.get("status") == "rejected":
                    # Transaction rejected by mempool
                    error_text = resp_json.get("error", "unknown error")
                    logger.debug(f"TX rejected: {tx_hash[:8]}... (nonce={nonce}): {error_text}")
                    # No client-side tracking needed - blockchain manages pending state
                    return False
                else:
                    # Transaction successfully sent to mempool
                    logger.debug(f"TX sent: {tx_hash[:8]}... (nonce={nonce})")
                    # No client-side tracking needed - blockchain manages pending state
                    return True
            else:
                # HTTP error
                error_text = resp.text
                logger.debug(f"TX HTTP error: {tx_hash[:8]}... (nonce={nonce}): {error_text}")
                return False
        except Exception as e:
            # Network error or other exception
            logger.debug(f"Broadcast error for {tx_hash[:8]}...: {e}")
            return False

    def generate_send_tx(self, sender=None) -> Transaction:
        """
        Generate SEND transaction.

        Args:
            sender: Optional sender account. If None, picks random account.
        """
        if sender is None:
            sender = random.choice(self.test_accounts)

        recipient = random.choice(self.test_accounts)

        # Don't send to self
        while recipient['address'] == sender['address']:
            recipient = random.choice(self.test_accounts)

        # Check sender balance and use safe amount (resilient to low balance)
        fee = 21000000  # 21M fee for TRANSFER
        balance = self._get_balance(sender['address'])
        reserve = 1 * (10**DECIMALS)  # Keep 1 CPC reserve for future fees
        max_safe_amount = max(0, balance - fee - reserve)

        # Use minimum of configured max and safe amount
        amount_max = min(self.config['amount_max'], max_safe_amount)
        amount_min = min(self.config['amount_min'], amount_max)

        # If balance too low, use minimal amount
        if amount_max < amount_min:
            amount = amount_min
        else:
            amount = random.randint(amount_min, amount_max)

        # Ethereum-style: get pending nonce directly from blockchain
        nonce = self._get_nonce(sender['address'])

        tx = Transaction(
            tx_type=TxType.TRANSFER,
            from_address=sender['address'],
            to_address=recipient['address'],
            amount=amount,
            fee=21000000,  # 21M fee for TRANSFER
            nonce=nonce,
            gas_price=1000,
            gas_limit=21000,
            pub_key=sender['public_key'],
            signature=""
        )

        # Sign transaction
        msg_hash = bytes.fromhex(tx.hash())
        private_key = bytes.fromhex(sender['private_key'])
        signature = sign(msg_hash, private_key)
        tx.signature = signature.hex()

        return tx

    def generate_delegate_tx(self, delegator=None) -> Transaction:
        """
        Generate DELEGATE transaction.

        Args:
            delegator: Optional delegator account. If None, picks random account.
        """
        if delegator is None:
            delegator = random.choice(self.test_accounts)

        validators = self._get_validators()

        if not validators:
            logger.warning("No validators available for delegation")
            return None

        validator = random.choice(validators)

        # Check delegator balance and use safe amount
        fee = 50000000  # 50M fee for STAKE
        balance = self._get_balance(delegator['address'])
        reserve = 1 * (10**DECIMALS)  # Keep 1 CPC reserve
        max_safe_amount = max(0, balance - fee - reserve)

        # Use safe delegation amount
        amount_max = min(10000 * (10**DECIMALS), max_safe_amount)
        amount_min = min(100 * (10**DECIMALS), amount_max)

        if amount_max < amount_min:
            amount = amount_min
        else:
            amount = random.randint(amount_min, amount_max)

        # Ethereum-style: get pending nonce directly from blockchain
        # No client-side nonce management needed
        nonce = self._get_nonce(delegator['address'])

        tx = Transaction(
            tx_type=TxType.STAKE,
            from_address=delegator['address'],
            to_address=validator['address'],
            amount=amount,
            fee=50000000,  # 50M fee for STAKE
            nonce=nonce,
            gas_price=1000,
            gas_limit=50000,
            pub_key=delegator['public_key'],
            signature="",
            payload={"pub_key": validator['pq_pub_key']}  # Include validator's pub_key in payload
        )

        # Sign
        msg_hash = bytes.fromhex(tx.hash())
        private_key = bytes.fromhex(delegator['private_key'])
        signature = sign(msg_hash, private_key)
        tx.signature = signature.hex()

        return tx

    def _get_account_lock(self, address: str) -> threading.Lock:
        """
        Get or create lock for specific account.

        Phase 1.4.3: Account-level locking to prevent race condition in nonce allocation.
        """
        with self.locks_lock:
            if address not in self.account_locks:
                self.account_locks[address] = threading.Lock()
            return self.account_locks[address]

    def generate_transaction(self, sender=None) -> Transaction:
        """
        Generate random transaction based on configured ratios.

        Args:
            sender: Optional sender account. If None, picks random account inside specific TX type method.
        """
        rand = random.random()

        if rand < self.config['send_ratio']:
            return self.generate_send_tx(sender=sender)
        elif rand < self.config['send_ratio'] + self.config['delegate_ratio']:
            return self.generate_delegate_tx(delegator=sender)
        else:
            # For now, default to SEND
            return self.generate_send_tx(sender=sender)

    def run(self, duration_seconds: int):
        """Run transaction generator for specified duration."""
        logger.info(f"Starting TX generator in {self.mode} mode")
        logger.info(f"TPS range: {self.config['tps_min']}-{self.config['tps_max']}")
        logger.info(f"Duration: {duration_seconds} seconds")

        end_time = datetime.now() + timedelta(seconds=duration_seconds)

        while datetime.now() < end_time:
            # Calculate TPS for this second
            tps = random.randint(self.config['tps_min'], self.config['tps_max'])
            delay = 1.0 / tps if tps > 0 else 1.0

            for _ in range(tps):
                if datetime.now() >= end_time:
                    break

                try:
                    # Ethereum-style: Simple TX generation with pending nonce
                    # No client-side locks or throttling needed
                    # Blockchain enforces queued TX limits per account (64)

                    # Pick random sender
                    sender = random.choice(self.test_accounts)

                    # Generate transaction (gets pending nonce from blockchain)
                    tx = self.generate_transaction(sender=sender)
                    if tx:
                        success = self._broadcast_tx(tx)

                        # Update stats
                        self.stats['total_sent'] += 1
                        if success:
                            self.stats['successful'] += 1
                        else:
                            self.stats['failed'] += 1

                        tx_type = tx.tx_type.value
                        self.stats['by_type'][tx_type] = self.stats['by_type'].get(tx_type, 0) + 1

                    # Sleep between transactions
                    time.sleep(delay)
                except KeyboardInterrupt:
                    logger.info("Interrupted by user")
                    self.print_stats()
                    self.cleanup()
                    return
                except Exception as e:
                    logger.error(f"Error generating tx: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")

            # Print stats every 60 seconds
            if self.stats['total_sent'] % (60 * tps) == 0:
                self.print_stats()

        logger.info("TX generator finished")
        self.print_stats()
        self.cleanup()

    def print_stats(self):
        """Print statistics."""
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
        avg_tps = self.stats['total_sent'] / elapsed if elapsed > 0 else 0

        # Get nonce manager stats
        nonce_stats = self.nonce_manager.get_stats()

        logger.info("=" * 60)
        logger.info(f"TX Generator Statistics ({self.mode} mode)")
        logger.info(f"Duration: {elapsed:.0f}s")
        logger.info(f"Total sent: {self.stats['total_sent']}")
        logger.info(f"Successful: {self.stats['successful']}")
        logger.info(f"Failed: {self.stats['failed']}")
        logger.info(f"Success rate: {100 * self.stats['successful'] / max(1, self.stats['total_sent']):.2f}%")
        logger.info(f"Average TPS: {avg_tps:.2f}")
        logger.info(f"By type: {self.stats['by_type']}")
        logger.info("")
        logger.info("NonceManager Statistics (Simplified tracking - no SSE):")
        logger.info(f"  Current pending: {nonce_stats['current_pending']}")
        logger.info(f"  Total confirmed: {nonce_stats['total_confirmed']}")
        logger.info(f"  Total failed: {nonce_stats['total_failed']}")
        logger.info(f"  Resyncs: {nonce_stats['resyncs']}")
        logger.info(f"  Addresses tracked: {nonce_stats['addresses_tracked']}")
        if 'event_confirmations' in nonce_stats:
            logger.info(f"  Event confirmations: {nonce_stats['event_confirmations']}")
        logger.info("=" * 60)

    def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up...")
        self.running = False
        if hasattr(self, 'tracker_thread') and self.tracker_thread.is_alive():
            self.tracker_thread.join(timeout=5)
        logger.info("Cleanup complete")


def main():
    parser = argparse.ArgumentParser(description='ComputeChain TX Generator')
    parser.add_argument('--node', default='http://localhost:8000', help='Node URL')
    parser.add_argument('--mode', choices=['low', 'medium', 'high', 'custom'], default='low',
                        help='Load mode')
    parser.add_argument('--duration', type=int, default=3600, help='Duration in seconds')
    parser.add_argument('--tps', type=int, help='Custom TPS (only for custom mode)')
    parser.add_argument('--send-ratio', type=float, help='SEND tx ratio (0.0-1.0)')
    parser.add_argument('--delegate-ratio', type=float, help='DELEGATE tx ratio')
    parser.add_argument('--undelegate-ratio', type=float, help='UNDELEGATE tx ratio')

    args = parser.parse_args()

    # Phase 1.4.1: Simplified tracking (no SSE dependency)
    generator = TxGenerator(args.node, args.mode)

    # Apply custom settings if provided
    if args.mode == 'custom':
        if args.tps:
            generator.config['tps_min'] = args.tps
            generator.config['tps_max'] = args.tps
        if args.send_ratio:
            generator.config['send_ratio'] = args.send_ratio
        if args.delegate_ratio:
            generator.config['delegate_ratio'] = args.delegate_ratio
        if args.undelegate_ratio:
            generator.config['undelegate_ratio'] = args.undelegate_ratio

    try:
        generator.run(args.duration)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        generator.print_stats()


if __name__ == '__main__':
    main()
