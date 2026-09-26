"""Runtime configuration: models, keys, paths."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(os.getenv("WIREFORGE_OUT_DIR", ROOT / "out"))
RESULTS_CSV = Path(os.getenv("WIREFORGE_RESULTS_CSV", ROOT / "bench" / "results.csv"))

# The model under test, and the previous Opus used as the baseline.
FORGE_MODEL = os.getenv("WIREFORGE_MODEL", "claude-opus-5-5")
BASELINE_MODEL = os.getenv("WIREFORGE_BASELINE_MODEL", "claude-opus-5")
EFFORT = os.getenv("WIREFORGE_EFFORT", "high")

# Needed only when the API key is not scoped to a workspace (the API then asks for this header).
ANTHROPIC_WORKSPACE_ID = os.getenv("ANTHROPIC_WORKSPACE_ID", "")


def anthropic_client_kwargs() -> dict:
    """Arguments for anthropic.Anthropic(); fails early with a readable message instead of a 401 mid-run."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add it.")
    headers = {"anthropic-workspace-id": ANTHROPIC_WORKSPACE_ID} if ANTHROPIC_WORKSPACE_ID else {}
    return {"max_retries": 4, "default_headers": headers}


ANAKIN_API_KEY = os.getenv("ANAKIN_API_KEY", "")
ANAKIN_CDP_URL = "wss://api.anakin.io/v1/browser-connect"

# Hard limits so a drifting agent cannot run forever.
MAX_AGENT_TURNS = int(os.getenv("WIREFORGE_MAX_TURNS", "60"))
MAX_REPAIR_ROUNDS = int(os.getenv("WIREFORGE_MAX_REPAIRS", "2"))
ACTION_TIMEOUT_S = 60

# Write actions may add to a cart, never pay or place an order.
BLOCKED_PATH_WORDS = ("checkout", "payment", "/pay", "place-order", "placeorder", "purchase")
