"""trace -> endpoint -> schema -> test -> verify -> self-correct, with one CSV row per run."""

from __future__ import annotations

import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import cancel, config
from .agent import RunStats
from .browser import BrowserSession
from .forge import Forge
from .verifier import Verifier

CSV_FIELDS = [
    "timestamp", "site", "goal", "model", "outcome", "action_id", "type", "declared_type", "emits", "repair_rounds",
    "forge_turns", "forge_tool_calls", "forge_tool_errors", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "verifier_model", "verifier_checks", "verifier_matched",
    "verifier_input_tokens", "verifier_output_tokens", "verifier_cache_read_tokens", "wall_s", "browser", "run_dir",
]


def recorded_type(declared: str, verdict: dict) -> str:
    """A write only counts as a write when the verifier saw the site store the change."""
    if declared == "write" and not verdict.get("write_persisted"):
        return "read"
    return declared


def _slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", urlparse(url).netloc.lower()).strip("-")


def new_run_dir(url: str, model: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = config.OUT_DIR / f"{_slug(url)}__{model}__{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _stage(run_dir: Path, stage: str, **data) -> None:
    """Pipeline milestones, in the same transcript the agents write, so the board can stream them."""
    with (run_dir / "transcript.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "agent": "pipeline", "kind": "stage",
                            "data": {"stage": stage, **data}}, default=str) + "\n")


def forge_action(url: str, goal: str, model: str, verifier_model: str | None = None,
                 headless: bool = True, run_dir: Path | None = None) -> dict:
    verifier_model = verifier_model or config.FORGE_MODEL
    run_dir = run_dir or new_run_dir(url, model)
    (run_dir / "request.json").write_text(json.dumps(
        {"url": url, "goal": goal, "model": model, "verifier_model": verifier_model}), encoding="utf-8")
    _stage(run_dir, "start", url=url, goal=goal, model=model, verifier_model=verifier_model)
    t0 = time.time()
    verdict: dict = {"passed": False, "checks": [], "summary": "not verified"}
    repairs = 0
    vstats = None
    forge: Forge | None = None
    stats = None
    backend = "anakin" if config.ANAKIN_API_KEY else "local-chromium"
    try:
        outcome, repairs, stats, verdict, vstats, forge, backend = _run(
            url, goal, model, verifier_model, headless, run_dir)
    except Exception as exc:  # a dead browser or API outage still leaves a row, not a silent gap
        outcome = "error"
        verdict = {"passed": False, "checks": [], "summary": f"run crashed: {type(exc).__name__}: {exc}"[:500]}
        _stage(run_dir, "error", error=verdict["summary"])
        forge = _CRASH.get("forge")
        stats = forge.agent.stats if forge else None
    _CRASH.clear()
    return _finish(url, goal, model, verifier_model, run_dir, t0, outcome, repairs, stats, verdict, vstats, forge, backend)


_CRASH: dict = {}  # the forge in progress, so a crash can still report how far it got


def _run(url, goal, model, verifier_model, headless, run_dir):
    verdict: dict = {"passed": False, "checks": [], "summary": "not verified"}
    repairs, vstats = 0, None
    with BrowserSession(headless=headless) as browser:
        backend = browser.backend
        _stage(run_dir, "trace", browser=backend)
        forge = _CRASH["forge"] = Forge(url, goal, model, run_dir, browser)
        stats = forge.run()
        while True:
            if cancel.requested():
                outcome = "cancelled"
                _stage(run_dir, "done", outcome="cancelled")
                break
            if not forge.passed:
                outcome = "no_working_action"
                break
            _stage(run_dir, "verify", action_id=forge.spec["action_id"] if forge.spec else "")
            # A fresh browser for the verifier: it must not inherit the forge's session.
            with browser.isolated() as vb:
                verifier = Verifier(forge.action_dir, verifier_model, run_dir, vb)
                verifier.run()
                verdict = verifier.verdict or verdict
                vstats = verifier.stats
            if verdict["passed"]:
                outcome = "verified"
                break
            if repairs >= config.MAX_REPAIR_ROUNDS:
                outcome = "rejected_by_verifier"
                break
            repairs += 1
            print(f"\n=== verifier rejected; repair round {repairs} ===\n", flush=True)
            _stage(run_dir, "repair", round=repairs)
            stats = forge.repair(json.dumps(verdict, indent=1))
    return outcome, repairs, stats, verdict, vstats, forge, backend


def _finish(url, goal, model, verifier_model, run_dir, t0, outcome, repairs, stats, verdict, vstats, forge, backend):
    spec = (forge.spec if forge else None) or {}
    s = stats or RunStats(model=model)
    summary = {
        "site": url, "goal": goal, "model": model, "outcome": outcome,
        "action_id": spec.get("action_id", ""),
        "type": recorded_type(spec.get("type", ""), verdict),
        "declared_type": spec.get("type", ""),
        "emits": forge.emits if forge else 0, "repair_rounds": repairs,
        "forge_turns": s.turns, "forge_tool_calls": s.tool_calls, "forge_tool_errors": s.tool_errors,
        "input_tokens": s.input_tokens, "output_tokens": s.output_tokens,
        "cache_read_tokens": s.cache_read_tokens, "cache_write_tokens": s.cache_write_tokens,
        "verifier_input_tokens": vstats.input_tokens if vstats else 0,
        "verifier_output_tokens": vstats.output_tokens if vstats else 0,
        "verifier_cache_read_tokens": vstats.cache_read_tokens if vstats else 0,
        "verifier_model": verifier_model, "verifier_checks": len(verdict.get("checks", [])),
        "verifier_matched": sum(1 for c in verdict.get("checks", []) if c.get("match")),
        "wall_s": round(time.time() - t0, 1), "browser": backend, "run_dir": run_dir.name,
    }
    (run_dir / "verdict.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    _append_csv(summary)
    _stage(run_dir, "done", outcome=outcome)
    return summary


def _append_csv(row: dict) -> None:
    path: Path = config.RESULTS_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        if header != CSV_FIELDS:
            # Columns changed: keep the old file intact under a new name instead of mixing layouts.
            path.rename(path.with_name(f"{path.stem}.legacy-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"))
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"), **row})
