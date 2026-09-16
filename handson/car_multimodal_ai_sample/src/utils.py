"""Small shared helpers: repo paths, config loading, determinism, threading.

Kept dependency-light so ML Jobs, Notebooks, and local dev can all import it.
Unchanged from the 45-minute handson (car_multimodal_handson/src/utils.py) —
this logic has no Snowflake dependency and needs no adaptation.
"""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    """Repository root (parent of this file's `src/` directory)."""
    return Path(__file__).resolve().parent.parent


def resolve(path: str | Path) -> Path:
    """Resolve a possibly-relative path against the repo root."""
    p = Path(path)
    return p if p.is_absolute() else repo_root() / p


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file (path relative to repo root is fine)."""
    cfg_path = resolve(path)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config not found: {cfg_path}. "
            f"Pass an existing --config, e.g. conf/prepare.yaml or conf/train.yaml."
        )
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def set_seed(seed: int) -> None:
    """Fix Python / NumPy / Torch RNGs so runs are reproducible across environments."""
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
    except ImportError:
        pass


def set_torch_threads(n: int) -> None:
    """Pin torch thread count so training time is comparable across environments."""
    try:
        import torch

        torch.set_num_threads(int(n))
    except ImportError:
        pass


def get_logger(name: str) -> logging.Logger:
    """A logger that prints one clean line per message to stderr."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
