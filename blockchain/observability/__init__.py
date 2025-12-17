# MIT License
# Copyright (c) 2025 Hashborn

"""
Observability Module (Phase 1.3)

Provides metrics, monitoring, and observability for ComputeChain.
"""

from .metrics import metrics_registry, update_metrics

__all__ = ['metrics_registry', 'update_metrics']
