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

        # Generate test accounts
        self.test_accounts = self._generate_test_accounts(100)
        logger.info(f"Generated {len(self.test_accounts)} test accounts")

    def _get_config(self, mode: str) -> Dict:
        """Get configuration for specified mode."""
        configs = {
            'low': {
                'tps_min': 1,
                'tps_max': 5,
                'send_ratio': 0.80,
                'delegate_ratio': 0.15,
                'undelegate_ratio': 0.05,
                'amount_min': 1 * DECIMALS,
                'amount_max': 100 * DECIMALS,
            },
            'medium': {
                'tps_min': 10,
                'tps_max': 50,
                'send_ratio': 0.60,
                'delegate_ratio': 0.20,
                'undelegate_ratio': 0.10,
                'update_validator_ratio': 0.10,
                'amount_min': 10 * DECIMALS,
                'amount_max': 1000 * DECIMALS,
            },
            'high': {
                'tps_min': 100,
                'tps_max': 500,
                'send_ratio': 0.50,
                'delegate_ratio': 0.25,
                'undelegate_ratio': 0.15,
                'update_validator_ratio': 0.10,
                'amount_min': 100 * DECIMALS,
                'amount_max': 10000 * DECIMALS,
            }
        }
        return configs.get(mode, configs['low'])

    def _generate_test_accounts(self, count: int) -> List[Dict]:
        """Generate test accounts for transactions."""
        accounts = []

        # Try to load existing test accounts
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

        return accounts

    def _get_nonce(self, address: str) -> int:
        """Get current nonce for address."""
        try:
            resp = requests.get(f"{self.node_url}/balance/{address}", timeout=5)
            if resp.status_code == 200:
                return resp.json()['nonce']
            return 0
        except Exception as e:
            logger.warning(f"Failed to get nonce for {address}: {e}")
            return 0

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
        try:
            tx_json = tx.model_dump()
            tx_json['tx_type'] = tx.tx_type.value  # Serialize enum

            resp = requests.post(
                f"{self.node_url}/tx/send",
                json=tx_json,
                timeout=5
            )

            if resp.status_code == 200:
                logger.debug(f"TX success: {tx.hash()[:8]}...")
                return True
            else:
                logger.warning(f"TX failed: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            return False

    def generate_send_tx(self) -> Transaction:
        """Generate SEND transaction."""
        sender = random.choice(self.test_accounts)
        recipient = random.choice(self.test_accounts)

        # Don't send to self
        while recipient['address'] == sender['address']:
            recipient = random.choice(self.test_accounts)

        amount = random.randint(self.config['amount_min'], self.config['amount_max'])
        nonce = self._get_nonce(sender['address'])

        tx = Transaction(
            tx_type=TxType.TRANSFER,
            from_address=sender['address'],
            to_address=recipient['address'],
            amount=amount,
            nonce=nonce,
            gas_price=1000,
            gas_limit=21000,
            data="",
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
        amount = random.randint(100 * DECIMALS, 10000 * DECIMALS)
        nonce = self._get_nonce(delegator['address'])

        tx = Transaction(
            tx_type=TxType.STAKE,
            from_address=delegator['address'],
            to_address=validator['address'],
            amount=amount,
            nonce=nonce,
            gas_price=1000,
            gas_limit=50000,
            data="",
            pub_key=delegator['public_key'],
            signature=""
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
                    tx = self.generate_transaction()
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
                    return
                except Exception as e:
                    logger.error(f"Error generating tx: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")

            # Print stats every 60 seconds
            if self.stats['total_sent'] % (60 * tps) == 0:
                self.print_stats()

        logger.info("TX generator finished")
        self.print_stats()

    def print_stats(self):
        """Print statistics."""
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
        avg_tps = self.stats['total_sent'] / elapsed if elapsed > 0 else 0

        logger.info("=" * 60)
        logger.info(f"TX Generator Statistics ({self.mode} mode)")
        logger.info(f"Duration: {elapsed:.0f}s")
        logger.info(f"Total sent: {self.stats['total_sent']}")
        logger.info(f"Successful: {self.stats['successful']}")
        logger.info(f"Failed: {self.stats['failed']}")
        logger.info(f"Success rate: {100 * self.stats['successful'] / max(1, self.stats['total_sent']):.2f}%")
        logger.info(f"Average TPS: {avg_tps:.2f}")
        logger.info(f"By type: {self.stats['by_type']}")
        logger.info("=" * 60)


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
