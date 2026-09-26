"""Wire Forge website: the landing page, the Forge Board, and a small JSON API over out/ and bench/.

Reads are public. Starting a run spends API credits, so it needs WIREFORGE_PASSCODE when one is set.
Run: python -m wireforge.web  (or uvicorn wireforge.web.server:app)
"""

from __future__ import annotations

import asyncio
import csv
import hmac
import json
import os
import statistics
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__, config
from ..pipeline import forge_action, new_run_dir

STATIC = Path(__file__).parent / "static"
PASSCODE = os.getenv("WIREFORGE_PASSCODE", "")
ALLOWED_MODELS = {config.FORGE_MODEL, config.BASELINE_MODEL, *config.EXTRA_MODELS}

app = FastAPI(title="Wire Forge", version=__version__, docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_lock = threading.Lock()  # one live run at a time: runs drive a real browser and cost credits
_active: dict[str, str] = {}  # run_id -> status


class RunRequest(BaseModel):
    url: str = Field(pattern=r"^https?://")
    goal: str = Field(min_length=5, max_length=400)
    model: str = config.FORGE_MODEL
    passcode: str = ""


# ------------------------------------------------------------------ helpers
def _run_dir(run_id: str) -> Path:
    d = (config.OUT_DIR / run_id).resolve()
    if d.parent != config.OUT_DIR.resolve() or not d.is_dir():
        raise HTTPException(404, "no such run")
    return d


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _status(run_id: str, d: Path) -> str:
    if run_id in _active:
        return _active[run_id]
    return "done" if (d / "summary.json").exists() else "interrupted"


def _csv_rows() -> list[dict]:
    if not config.RESULTS_CSV.exists():
        return []
    with config.RESULTS_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ pages
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.svg")
def favicon() -> FileResponse:
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


# ------------------------------------------------------------------ read API
@app.get("/api/meta")
def meta() -> dict:
    return {
        "version": __version__, "model": config.FORGE_MODEL, "baseline_model": config.BASELINE_MODEL,
        "models": [config.FORGE_MODEL, config.BASELINE_MODEL, *config.EXTRA_MODELS],
        "browser": "anakin" if config.ANAKIN_API_KEY else "local-chromium",
        "passcode_required": bool(PASSCODE), "busy": bool(_active and "running" in _active.values()),
        "api_key_present": bool(os.getenv("ANTHROPIC_API_KEY")),
    }


@app.get("/api/tally")
def tally() -> dict:
    """Every number on the site comes from here, and this comes only from bench/results.csv."""
    rows = _csv_rows()
    verified = [r for r in rows if r["outcome"] == "verified"]
    minutes = [float(r["wall_s"]) / 60 for r in verified if r.get("wall_s")]
    by_model: dict[str, dict] = {}
    for r in rows:
        m = by_model.setdefault(r["model"], {"runs": 0, "verified": 0, "wall_s": [], "repairs": []})
        m["runs"] += 1
        if r["outcome"] == "verified":
            m["verified"] += 1
            m["wall_s"].append(float(r["wall_s"]))
        m["repairs"].append(int(r["repair_rounds"] or 0))
    models = {
        k: {"runs": v["runs"], "verified": v["verified"],
            "median_min": round(statistics.median(v["wall_s"]) / 60, 1) if v["wall_s"] else None,
            "avg_repairs": round(statistics.mean(v["repairs"]), 2) if v["repairs"] else None}
        for k, v in by_model.items()
    }
    return {
        "runs": len(rows),
        "verified": len(verified),
        "sites": len({r["site"] for r in verified}),
        "write_actions": sum(1 for r in verified if r["type"] == "write"),
        "median_min": round(statistics.median(minutes), 1) if minutes else None,
        "models": models,
    }


@app.get("/api/head2head")
def head2head() -> list[dict]:
    """Receipts from bench/head2head/*.json (the scorecard's format), with seconds to ship."""
    from datetime import datetime

    from ..scorecard import SHIPPED, load

    out = []
    for r in load():
        ev = r.get("events", [])
        shipped = next((e["ts"] for e in ev if e["status"] == SHIPPED), None)
        secs = (datetime.fromisoformat(shipped) - datetime.fromisoformat(ev[0]["ts"])).total_seconds() if ev and shipped else None
        out.append({**r, "seconds_to_ship": secs})
    return out


@app.get("/api/results")
def results() -> list[dict]:
    return _csv_rows()[::-1]


@app.get("/api/runs")
def runs() -> list[dict]:
    out = []
    if config.OUT_DIR.exists():
        for d in sorted(config.OUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            req = _read_json(d / "request.json") or {}
            summ = _read_json(d / "summary.json") or {}
            out.append({"id": d.name, "status": _status(d.name, d), "url": req.get("url") or summ.get("site"),
                        "goal": req.get("goal") or summ.get("goal"), "model": req.get("model") or summ.get("model"),
                        "outcome": summ.get("outcome"), "action_id": summ.get("action_id"),
                        "type": summ.get("type"), "wall_s": summ.get("wall_s")})
    return out[:100]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    d = _run_dir(run_id)
    code = d / "action" / "action.py"
    return {
        "id": run_id, "status": _status(run_id, d),
        "request": _read_json(d / "request.json"), "summary": _read_json(d / "summary.json"),
        "verdict": _read_json(d / "verdict.json"), "spec": _read_json(d / "action" / "spec.json"),
        "test_params": _read_json(d / "action" / "test_params.json"),
        "code": code.read_text(encoding="utf-8") if code.exists() else None,
        "last_run": _read_json(d / "last_run.json"),
    }


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    """Server-sent events: tails transcript.jsonl until the run is finished and fully read."""
    d = _run_dir(run_id)
    path = d / "transcript.jsonl"

    async def stream():
        pos, idle = 0, 0
        while not await request.is_disconnected():
            lines = []
            if path.exists():
                with path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                # keep a partial last line for the next read
                cut = chunk.rfind(b"\n") + 1
                lines, pos = chunk[:cut].decode("utf-8").splitlines(), pos + cut
            for line in lines:
                yield f"data: {line}\n\n"
            if lines:
                idle = 0
            elif _status(run_id, d) != "running":
                yield "event: end\ndata: {}\n\n"
                return
            else:
                idle += 1
                if idle % 30 == 0:
                    yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ start a run
@app.post("/api/runs", status_code=202)
def start_run(body: RunRequest) -> dict:
    if PASSCODE and not hmac.compare_digest(body.passcode, PASSCODE):
        raise HTTPException(403, "wrong passcode")
    if body.model not in ALLOWED_MODELS:
        raise HTTPException(400, f"model must be one of {sorted(ALLOWED_MODELS)}")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "ANTHROPIC_API_KEY is not set on the server")
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "a run is already in progress; watch it on the board")
    run_dir = new_run_dir(body.url, body.model)
    run_id = run_dir.name
    _active[run_id] = "running"

    def work() -> None:
        try:
            forge_action(body.url, body.goal, body.model, run_dir=run_dir)
            _active[run_id] = "done"
        except Exception as exc:
            _active[run_id] = "error"
            with (run_dir / "transcript.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"agent": "pipeline", "kind": "stage", "data": {
                    "stage": "error", "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc()[-2000:]}}) + "\n")
        finally:
            _lock.release()

    threading.Thread(target=work, name=f"run-{run_id}", daemon=True).start()
    return {"id": run_id}
