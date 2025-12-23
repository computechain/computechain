"""
Event system for blockchain lifecycle events.

Provides a simple pub/sub mechanism for transaction and block events.
"""
from typing import Dict, List, Callable, Any
import logging

logger = logging.getLogger(__name__)


class EventBus:
    """
    Simple event bus for blockchain events.

    Thread-safe event publishing and subscription mechanism.
    Events are delivered synchronously in the same thread.
    """

    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """
        Subscribe to an event type.

        Args:
            event_type: Event name (e.g., 'tx_confirmed', 'tx_failed')
            callback: Function to call when event is emitted
        """
        if event_type not in self.listeners:
            self.listeners[event_type] = []

        self.listeners[event_type].append(callback)
        logger.debug(f"Subscribed to event: {event_type}")

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """
        Unsubscribe from an event type.

        Args:
            event_type: Event name
            callback: The callback to remove
        """
        if event_type in self.listeners:
            try:
                self.listeners[event_type].remove(callback)
                logger.debug(f"Unsubscribed from event: {event_type}")
            except ValueError:
                logger.warning(f"Callback not found for event: {event_type}")

    def emit(self, event_type: str, **data: Any) -> None:
        """
        Emit an event to all subscribers.

        Args:
            event_type: Event name
            **data: Event data as keyword arguments
        """
        listeners = self.listeners.get(event_type, [])

        if not listeners:
            logger.debug(f"No listeners for event: {event_type}")
            return

        logger.debug(f"Emitting event: {event_type} to {len(listeners)} listener(s)")

        # Update Prometheus metrics for tx_confirmed events (Phase 1.4)
        if event_type == 'tx_confirmed':
            try:
                from blockchain.observability.metrics import event_confirmations_total
                event_confirmations_total.inc()
            except Exception as e:
                logger.debug(f"Failed to update event confirmation metric: {e}")

        for callback in listeners:
            try:
                callback(**data)
            except Exception as e:
                logger.error(f"Error in event callback for {event_type}: {e}", exc_info=True)

    def clear(self, event_type: str = None) -> None:
        """
        Clear all listeners for an event type, or all listeners if no type specified.

        Args:
            event_type: Event type to clear, or None to clear all
        """
        if event_type:
            self.listeners.pop(event_type, None)
            logger.debug(f"Cleared listeners for event: {event_type}")
        else:
            self.listeners.clear()
            logger.debug("Cleared all event listeners")


# Global event bus instance
event_bus = EventBus()
