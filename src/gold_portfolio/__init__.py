"""Composite Revised + Bear portfolio workers for GOLD.i# and GOLDm#."""

from .config import PortfolioWorkerConfig, load_worker_config
from .worker import CompositePortfolioWorker

__all__ = ["CompositePortfolioWorker", "PortfolioWorkerConfig", "load_worker_config"]
