#!/usr/bin/env python3
"""
SSE (Server-Sent Events) Client for EventBus

Phase 1.4: Enables cross-process event subscription via HTTP.
"""

import requests
import threading
import logging
import json
import time
from typing import Callable, Dict

logger = logging.getLogger(__name__)


class SSEClient:
    """
    HTTP Server-Sent Events client for subscribing to blockchain events.

    Connects to /events/stream endpoint and calls callbacks on events.
    """

    def __init__(self, node_url: str = "http://localhost:8000"):
        """
        Args:
            node_url: Base URL of the blockchain node
        """
        self.node_url = node_url
        self.stream_url = f"{node_url}/events/stream"
        self.callbacks: Dict[str, list] = {}  # event_type -> [callbacks]
        self.running = False
        self.thread = None
        self.reconnect_delay = 5  # Seconds to wait before reconnecting

    def subscribe(self, event_type: str, callback: Callable):
        """
        Subscribe to an event type.

        Args:
            event_type: Event name (tx_confirmed, tx_failed, block_created)
            callback: Function to call when event is received
        """
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []

        self.callbacks[event_type].append(callback)
        logger.debug(f"Subscribed to SSE event: {event_type}")

    def start(self):
        """Start listening to SSE stream in background thread."""
        if self.running:
            logger.warning("SSE client already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        logger.info(f"✅ SSE client started: {self.stream_url}")

    def stop(self):
        """Stop listening to SSE stream."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("SSE client stopped")

    def _listen_loop(self):
        """Main event listening loop with auto-reconnect."""
        while self.running:
            try:
                self._connect_and_listen()
            except Exception as e:
                logger.error(f"SSE connection error: {e}")

            if self.running:
                logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                time.sleep(self.reconnect_delay)

    def _connect_and_listen(self):
        """Connect to SSE stream and process events."""
        logger.info(f"Connecting to SSE stream: {self.stream_url}")

        try:
            response = requests.get(
                self.stream_url,
                stream=True,
                timeout=None,  # No timeout for streaming
                headers={"Accept": "text/event-stream"}
            )
            response.raise_for_status()

            logger.info("✅ Connected to SSE stream")

            # Process events line by line
            for line in response.iter_lines():
                if not self.running:
                    break

                if line:
                    line = line.decode('utf-8')

                    # SSE format: "data: {...}"
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        try:
                            event_data = json.loads(data_str)
                            self._handle_event(event_data)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON in SSE event: {e}")
                    elif line.startswith(": "):
                        # Keep-alive ping, ignore
                        pass

        except requests.exceptions.RequestException as e:
            logger.error(f"SSE request error: {e}")
            raise

    def _handle_event(self, event_data: dict):
        """
        Handle received event by calling appropriate callbacks.

        Args:
            event_data: Event data with 'type' field
        """
        event_type = event_data.get("type")
        if not event_type:
            logger.warning(f"Event without type: {event_data}")
            return

        # Call all callbacks for this event type
        callbacks = self.callbacks.get(event_type, [])
        for callback in callbacks:
            try:
                callback(**event_data)
            except Exception as e:
                logger.error(f"Error in SSE callback for {event_type}: {e}")

        if callbacks:
            logger.debug(f"SSE event processed: {event_type}")


if __name__ == "__main__":
    # Test SSE client
    logging.basicConfig(level=logging.DEBUG)

    client = SSEClient("http://localhost:8000")

    def on_tx_confirmed(**data):
        print(f"✅ TX Confirmed: {data.get('tx_hash', 'unknown')[:8]}... at block {data.get('block_height', '?')}")

    def on_tx_failed(**data):
        print(f"❌ TX Failed: {data.get('tx_hash', 'unknown')[:8]}...")

    client.subscribe("tx_confirmed", on_tx_confirmed)
    client.subscribe("tx_failed", on_tx_failed)

    client.start()

    try:
        print("Listening for events... (Ctrl+C to stop)")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        client.stop()
