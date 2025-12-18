#!/usr/bin/env python3
"""
Phase 1.4 - System Monitor
Мониторинг метрик blockchain и системных ресурсов
"""

import argparse
import time
import requests
import psutil
import csv
import logging
from datetime import datetime
from typing import Dict, List
import os

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class SystemMonitor:
    """Monitor for blockchain and system metrics."""

    def __init__(self, node_url: str, interval: int = 60):
        self.node_url = node_url
        self.interval = interval
        self.metrics_history: List[Dict] = []

        # Alert thresholds
        self.alert_cpu = 80.0
        self.alert_ram = 90.0
        self.alert_disk = 90.0
        self.alert_block_time = 15.0

    def get_blockchain_metrics(self) -> Dict:
        """Get blockchain metrics from node."""
        try:
            # Get status
            status_resp = requests.get(f"{self.node_url}/status", timeout=5)
            if status_resp.status_code != 200:
                return {}

            status = status_resp.json()

            # Get validators
            validators_resp = requests.get(f"{self.node_url}/validators", timeout=5)
            validators = validators_resp.json() if validators_resp.status_code == 200 else []

            # Get metrics from Prometheus endpoint
            metrics_resp = requests.get(f"{self.node_url}/metrics", timeout=5)
            prometheus_metrics = self._parse_prometheus(metrics_resp.text) if metrics_resp.status_code == 200 else {}

            return {
                'timestamp': datetime.now().isoformat(),
                'height': status.get('height', 0),
                'network': status.get('network', 'unknown'),
                'epoch': status.get('epoch', 0),
                'mempool_size': status.get('mempool_size', 0),
                'validator_count': len(validators),
                'active_validators': len([v for v in validators if v.get('is_active', False)]),
                **prometheus_metrics
            }
        except Exception as e:
            logger.error(f"Failed to get blockchain metrics: {e}")
            return {}

    def get_system_metrics(self) -> Dict:
        """Get system resource metrics."""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_per_core = psutil.cpu_percent(interval=1, percpu=True)

            # Memory
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()

            # Disk
            disk = psutil.disk_usage('/')
            disk_io = psutil.disk_io_counters()

            # Network
            net_io = psutil.net_io_counters()

            # Process count
            process_count = len(psutil.pids())

            return {
                'cpu_percent': cpu_percent,
                'cpu_count': psutil.cpu_count(),
                'memory_used_gb': memory.used / (1024**3),
                'memory_total_gb': memory.total / (1024**3),
                'memory_percent': memory.percent,
                'swap_used_gb': swap.used / (1024**3),
                'swap_percent': swap.percent,
                'disk_used_gb': disk.used / (1024**3),
                'disk_total_gb': disk.total / (1024**3),
                'disk_percent': disk.percent,
                'disk_read_mb': disk_io.read_bytes / (1024**2) if disk_io else 0,
                'disk_write_mb': disk_io.write_bytes / (1024**2) if disk_io else 0,
                'net_sent_mb': net_io.bytes_sent / (1024**2),
                'net_recv_mb': net_io.bytes_recv / (1024**2),
                'process_count': process_count
            }
        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            return {}

    def _parse_prometheus(self, text: str) -> Dict:
        """Parse Prometheus metrics text format."""
        metrics = {}
        for line in text.split('\n'):
            if line.startswith('#') or not line.strip():
                continue

            try:
                # Simple parsing (key value)
                if ' ' in line:
                    key, value = line.rsplit(' ', 1)
                    # Remove labels if present
                    if '{' in key:
                        key = key.split('{')[0]
                    metrics[key] = float(value)
            except:
                pass

        return metrics

    def check_alerts(self, metrics: Dict):
        """Check for alert conditions."""
        alerts = []

        # CPU alert
        if metrics.get('cpu_percent', 0) > self.alert_cpu:
            alerts.append(f"⚠️  HIGH CPU: {metrics['cpu_percent']:.1f}%")

        # RAM alert
        if metrics.get('memory_percent', 0) > self.alert_ram:
            alerts.append(f"⚠️  HIGH RAM: {metrics['memory_percent']:.1f}%")

        # Disk alert
        if metrics.get('disk_percent', 0) > self.alert_disk:
            alerts.append(f"⚠️  HIGH DISK: {metrics['disk_percent']:.1f}%")

        # Block time alert (if available from Prometheus)
        block_time = metrics.get('computechain_block_time_seconds', 0)
        if block_time > self.alert_block_time:
            alerts.append(f"⚠️  SLOW BLOCKS: {block_time:.1f}s")

        # Mempool size alert
        if metrics.get('mempool_size', 0) > 10000:
            alerts.append(f"⚠️  LARGE MEMPOOL: {metrics['mempool_size']}")

        if alerts:
            logger.warning("ALERTS TRIGGERED:")
            for alert in alerts:
                logger.warning(f"  {alert}")

    def collect_metrics(self) -> Dict:
        """Collect all metrics."""
        blockchain_metrics = self.get_blockchain_metrics()
        system_metrics = self.get_system_metrics()

        metrics = {
            **blockchain_metrics,
            **system_metrics
        }

        self.metrics_history.append(metrics)
        return metrics

    def print_metrics(self, metrics: Dict):
        """Print metrics in readable format."""
        print("\n" + "=" * 80)
        print(f"📊 System Monitor - {metrics.get('timestamp', datetime.now().isoformat())}")
        print("=" * 80)

        # Blockchain metrics
        print("\n🔗 Blockchain:")
        height = metrics.get('height', 'N/A')
        print(f"  Height: {height:,}" if isinstance(height, int) else f"  Height: {height}")
        print(f"  Epoch: {metrics.get('epoch', 'N/A')}")
        print(f"  Network: {metrics.get('network', 'N/A')}")
        mempool = metrics.get('mempool_size', 'N/A')
        print(f"  Mempool: {mempool:,} txs" if isinstance(mempool, int) else f"  Mempool: {mempool} txs")
        print(f"  Validators: {metrics.get('active_validators', 'N/A')}/{metrics.get('validator_count', 'N/A')}")

        # System metrics
        print("\n💻 System Resources:")
        print(f"  CPU: {metrics.get('cpu_percent', 0):.1f}% ({metrics.get('cpu_count', 0)} cores)")
        print(f"  RAM: {metrics.get('memory_used_gb', 0):.2f}/{metrics.get('memory_total_gb', 0):.2f} GB ({metrics.get('memory_percent', 0):.1f}%)")
        print(f"  Disk: {metrics.get('disk_used_gb', 0):.2f}/{metrics.get('disk_total_gb', 0):.2f} GB ({metrics.get('disk_percent', 0):.1f}%)")
        print(f"  Processes: {metrics.get('process_count', 'N/A')}")

        # Performance metrics (from Prometheus)
        if 'computechain_block_time_seconds' in metrics:
            print("\n⚡ Performance:")
            print(f"  Block time: {metrics.get('computechain_block_time_seconds', 0):.2f}s")
            print(f"  TPS: {metrics.get('computechain_transactions_per_second', 0):.2f}")

        if 'computechain_total_supply' in metrics:
            print("\n💰 Economics:")
            decimals = 10**18
            print(f"  Total Supply: {metrics.get('computechain_total_supply', 0) / decimals:,.2f} CPC")
            print(f"  Total Minted: {metrics.get('computechain_total_minted', 0) / decimals:,.2f} CPC")
            print(f"  Total Burned: {metrics.get('computechain_total_burned', 0) / decimals:,.2f} CPC")

        print("=" * 80)

    def save_to_csv(self, filepath: str):
        """Save metrics history to CSV."""
        if not self.metrics_history:
            logger.warning("No metrics to save")
            return

        try:
            # Get all keys from all metrics
            fieldnames = set()
            for metrics in self.metrics_history:
                fieldnames.update(metrics.keys())
            fieldnames = sorted(fieldnames)

            with open(filepath, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.metrics_history)

            logger.info(f"Saved {len(self.metrics_history)} metric samples to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save CSV: {e}")

    def run(self, duration: int = None, output: str = None):
        """Run monitor for specified duration."""
        logger.info(f"Starting monitor (interval: {self.interval}s)")

        start_time = time.time()
        sample_count = 0

        try:
            while True:
                # Collect metrics
                metrics = self.collect_metrics()

                # Print
                self.print_metrics(metrics)

                # Check alerts
                self.check_alerts(metrics)

                sample_count += 1

                # Save periodically if output specified
                if output and sample_count % 10 == 0:
                    self.save_to_csv(output)

                # Check duration
                if duration and (time.time() - start_time) >= duration:
                    logger.info(f"Monitor duration reached ({duration}s)")
                    break

                # Sleep until next interval
                time.sleep(self.interval)

        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")

        finally:
            # Save final metrics
            if output:
                self.save_to_csv(output)

            logger.info(f"Collected {sample_count} metric samples")


def main():
    parser = argparse.ArgumentParser(description='ComputeChain System Monitor')
    parser.add_argument('--node', default='http://localhost:8000', help='Node URL')
    parser.add_argument('--interval', type=int, default=60, help='Collection interval (seconds)')
    parser.add_argument('--duration', type=int, help='Run duration (seconds)')
    parser.add_argument('--output', help='Output CSV file')
    parser.add_argument('--alert-cpu', type=float, default=80.0, help='CPU alert threshold (%)')
    parser.add_argument('--alert-ram', type=float, default=90.0, help='RAM alert threshold (%)')
    parser.add_argument('--alert-disk', type=float, default=90.0, help='Disk alert threshold (%)')
    parser.add_argument('--watch-txs', action='store_true', help='Watch transactions only')

    args = parser.parse_args()

    monitor = SystemMonitor(args.node, args.interval)
    monitor.alert_cpu = args.alert_cpu
    monitor.alert_ram = args.alert_ram
    monitor.alert_disk = args.alert_disk

    # Ensure output directory exists
    if args.output:
        os.makedirs(os.path.dirname(args.output) or 'logs', exist_ok=True)

    monitor.run(duration=args.duration, output=args.output)


if __name__ == '__main__':
    main()
