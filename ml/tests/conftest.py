"""Shared fixtures for the GPU-worker tests.

Everything here runs without torch, models or a GPU. When the backend package is importable (its
dependencies installed), ``test_contract.py`` additionally drives the real FastAPI app.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# The backend builds a module-level app from HL_* variables on import, so they must be set first.
_SCRATCH = Path(tempfile.mkdtemp(prefix="heritage-gpu-tests-"))
for _key, _value in {
    "HL_ENV": "test",
    "HL_DATABASE_URL": f"sqlite+aiosqlite:///{(_SCRATCH / 'default.db').as_posix()}",
    "HL_STORAGE_DIR": str(_SCRATCH / "storage"),
    "HL_EMBEDDER": "hashing",
    "HL_ENABLE_IMAGE_SEARCH": "false",
    "HL_LOG_LEVEL": "WARNING",
}.items():
    os.environ.setdefault(_key, _value)

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if (BACKEND / "app").is_dir() and str(BACKEND) not in sys.path:
    sys.path.append(str(BACKEND))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    shutil.rmtree(_SCRATCH, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_heritage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's HERITAGE_* variables from leaking into config tests."""
    for key in list(os.environ):
        if key.startswith("HERITAGE_"):
            monkeypatch.delenv(key)
