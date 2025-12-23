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

        # Nonce Manager with event-based transaction tracking (Phase 1.4)
        # Aggressive cleanup has been REMOVED for safety
        self.nonce_manager = NonceManager(self._get_nonce)

        # Set running flag BEFORE starting threads
        self.running = True

        # Start HTTP polling for transaction confirmations (Phase 1.4)
        self._subscribe_to_events()
        logger.info("Event-based transaction tracking ENABLED (Phase 1.4)")

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
                'amount_min': 100 * (10**DECIMALS),
                'amount_max': 10000 * (10**DECIMALS),
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
                    nonce = self.nonce_manager.get_next_nonce(faucet['address'])

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
        """Get current nonce for address from blockchain."""
        try:
            resp = requests.get(f"{self.node_url}/balance/{address}", timeout=5)
            if resp.status_code == 200:
                return resp.json()['nonce']
            return 0
        except Exception as e:
            logger.warning(f"Failed to get nonce for {address}: {e}")
            return 0

    def _subscribe_to_events(self):
        """
        Subscribe to blockchain events for transaction lifecycle tracking (Phase 1.4).

        Uses HTTP polling of Transaction Receipt API (/tx/{hash}/receipt) to check
        TX confirmation status. This works across process boundaries (unlike in-process EventBus).
        """
        import threading

        # Start background thread for polling receipts
        self.receipt_poll_thread = threading.Thread(
            target=self._poll_transaction_receipts,
            daemon=True,
            name="TxReceiptPoller"
        )
        self.receipt_poll_thread.start()
        logger.info("Started TX receipt polling thread (HTTP-based event tracking)")

    def _poll_transaction_receipts(self):
        """
        Background thread that polls Transaction Receipt API to check TX confirmations.

        Checks pending transactions every 2 seconds using GET /tx/{hash}/receipt API.
        When a TX is confirmed, notifies NonceManager via on_tx_confirmed().
        """
        import time

        logger.info("TX receipt poller started")
        poll_count = 0

        while self.running:
            try:
                poll_count += 1

                # Get copy of currently pending TX hashes from NonceManager
                with self.nonce_manager.lock:
                    pending_hashes = list(self.nonce_manager.pending_hashes)

                if poll_count % 10 == 0:  # Log every 20 seconds
                    logger.info(f"Receipt poller: checking {len(pending_hashes)} pending TXs (poll #{poll_count})")

                # Check each pending TX (batch of up to 20 at a time to avoid overwhelming API)
                batch_size = 20
                checked = 0
                confirmed_count = 0

                for tx_hash in pending_hashes[:batch_size]:
                    try:
                        # Query receipt API
                        resp = requests.get(
                            f"{self.node_url}/tx/{tx_hash}/receipt",
                            timeout=2
                        )

                        checked += 1

                        if resp.status_code == 200:
                            receipt = resp.json()

                            # If TX is confirmed, notify NonceManager
                            if receipt.get('status') == 'confirmed':
                                # Find the pending TX to get address and nonce
                                with self.nonce_manager.lock:
                                    for addr, pending_txs in self.nonce_manager.pending_txs.items():
                                        for ptx in pending_txs:
                                            if ptx.tx_hash == tx_hash and not ptx.confirmed:
                                                # Notify confirmation
                                                self.nonce_manager.on_tx_confirmed(
                                                    addr,
                                                    tx_hash,
                                                    ptx.nonce
                                                )
                                                confirmed_count += 1
                                                logger.info(f"✅ TX confirmed via API polling: {tx_hash[:16]}... (block {receipt.get('block_height')})")
                                                break

                        elif resp.status_code == 404:
                            # TX not found - might be too old or failed
                            if poll_count % 30 == 0:  # Log occasionally
                                logger.debug(f"TX not found in receipt store: {tx_hash[:16]}...")

                    except Exception as e:
                        # Individual TX check failure - continue with others
                        if poll_count % 30 == 0:
                            logger.debug(f"Error checking TX {tx_hash[:16]}...: {e}")

                if confirmed_count > 0:
                    logger.info(f"Receipt poller: confirmed {confirmed_count} TXs out of {checked} checked")

                # Sleep between poll cycles
                time.sleep(2)

            except Exception as e:
                logger.error(f"Error in receipt poller: {e}")
                time.sleep(5)

    def _transaction_tracker(self):
        """
        Background thread for tracking pending transactions.
        Checks for timeouts and syncs with blockchain periodically.
        """
        logger.info("Transaction tracker started")

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
                # Transaction successfully sent to mempool
                self.nonce_manager.on_tx_sent(from_address, tx_hash, nonce)
                logger.debug(f"TX sent: {tx_hash[:8]}... (nonce={nonce})")
                return True
            else:
                # Transaction rejected by mempool
                error_text = resp.text
                self.nonce_manager.on_tx_failed(from_address, tx_hash, nonce, error_text)
                logger.warning(f"TX rejected: {tx_hash[:8]}... (nonce={nonce}): {error_text}")
                return False
        except Exception as e:
            # Network error or other exception
            self.nonce_manager.on_tx_failed(from_address, tx_hash, nonce, str(e))
            logger.error(f"Broadcast error for {tx_hash[:8]}...: {e}")
            return False

    def generate_send_tx(self) -> Transaction:
        """Generate SEND transaction."""
        sender = random.choice(self.test_accounts)
        recipient = random.choice(self.test_accounts)

        # Don't send to self
        while recipient['address'] == sender['address']:
            recipient = random.choice(self.test_accounts)

        amount = random.randint(self.config['amount_min'], self.config['amount_max'])
        nonce = self.nonce_manager.get_next_nonce(sender['address'])

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

    def generate_delegate_tx(self) -> Transaction:
        """Generate DELEGATE transaction."""
        delegator = random.choice(self.test_accounts)
        validators = self._get_validators()

        if not validators:
            logger.warning("No validators available for delegation")
            return None

        validator = random.choice(validators)
        amount = random.randint(100 * (10**DECIMALS), 10000 * (10**DECIMALS))
        nonce = self.nonce_manager.get_next_nonce(delegator['address'])

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

    def generate_transaction(self) -> Transaction:
        """Generate random transaction based on configured ratios."""
        rand = random.random()

        if rand < self.config['send_ratio']:
            return self.generate_send_tx()
        elif rand < self.config['send_ratio'] + self.config['delegate_ratio']:
            return self.generate_delegate_tx()
        else:
            # For now, default to SEND
            return self.generate_send_tx()

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
                    # Generate transaction
                    tx = self.generate_transaction()
                    if tx:
                        # Check if sender has too many pending transactions
                        pending_count = self.nonce_manager.get_pending_count(tx.from_address)

                        if pending_count > 10:  # Max 10 pending TX per account
                            logger.debug(f"Too many pending TX ({pending_count}) for {tx.from_address[:10]}..., skipping")
                            time.sleep(delay)
                            continue

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
        logger.info("NonceManager Statistics (Event-based tracking only):")
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

    # Phase 1.4: Event-based tracking is now the ONLY mode (aggressive cleanup removed)
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
