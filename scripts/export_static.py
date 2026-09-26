"""Export the website as a static snapshot for Vercel (or any static host).

python scripts/export_static.py  ->  dist/ with the page, assets, and every /api response
pre-rendered as JSON. Live forging stays on the machine that runs the real server; the
snapshot serves everything else: tally, chart, audits, run list, and full run replays.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wireforge import config  # noqa: E402
from wireforge.web import server  # noqa: E402

DIST = ROOT / "dist"


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "api" / "runs").mkdir(parents=True)

    # page + assets (the page references /static/... so keep that layout)
    shutil.copytree(server.STATIC, DIST / "static")
    shutil.copy(server.STATIC / "index.html", DIST / "index.html")
    shutil.copy(server.STATIC / "favicon.svg", DIST / "favicon.svg")

    meta = server.meta()
    meta.update(static=True, passcode_required=False, api_key_present=False)
    (DIST / "api" / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (DIST / "api" / "tally.json").write_text(json.dumps(server.tally()), encoding="utf-8")
    (DIST / "api" / "results.json").write_text(json.dumps(server.results()), encoding="utf-8")

    runs = server.runs()
    for r in runs:
        r["status"] = "done" if r["status"] in ("done", "running") else r["status"]
    (DIST / "api" / "runs.json").write_text(json.dumps(runs), encoding="utf-8")

    for r in runs:
        rid = r["id"]
        detail = server.run_detail(rid)
        detail["status"] = r["status"]
        (DIST / "api" / "runs" / f"{rid}.json").write_text(json.dumps(detail, default=str), encoding="utf-8")
        events = []
        t = config.OUT_DIR / rid / "transcript.jsonl"
        if t.exists():
            for line in t.read_text(encoding="utf-8").splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        d = DIST / "api" / "runs" / rid
        d.mkdir(exist_ok=True)
        (d / "events.json").write_text(json.dumps(events, default=str), encoding="utf-8")

    (DIST / "vercel.json").write_text(json.dumps({
        "rewrites": [
            {"source": "/api/runs/:id/events", "destination": "/api/runs/:id/events.json"},
            {"source": "/api/runs/:id", "destination": "/api/runs/:id.json"},
            {"source": "/api/:name", "destination": "/api/:name.json"},
        ]
    }, indent=1), encoding="utf-8")

    n = sum(1 for _ in DIST.rglob("*") if _.is_file())
    print(f"wrote {DIST} ({len(runs)} runs, {n} files)")


if __name__ == "__main__":
    main()
