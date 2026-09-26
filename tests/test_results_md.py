"""results_md renders only what is in the CSV — empty CSV, empty page."""

import csv
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "results_md", Path(__file__).parents[1] / "scripts" / "results_md.py")
results_md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(results_md)

from wireforge.pipeline import CSV_FIELDS  # noqa: E402


def _row(**kw) -> dict:
    row = {k: "" for k in CSV_FIELDS}
    row.update(kw)
    return row


def test_empty_csv_says_so(tmp_path):
    assert "No runs recorded yet" in results_md.render([])


def test_render_uses_only_csv_rows(tmp_path):
    rows = [
        _row(timestamp="2026-09-26T10:00:00", site="https://www.a.test/", goal="find buses",
             model="m-new", outcome="verified", action_id="a_test.search", type="read",
             verifier_checks="3", verifier_matched="3", repair_rounds="0",
             forge_tool_errors="1", wall_s="240"),
        _row(timestamp="2026-09-26T11:00:00", site="https://b.test/", goal="add to cart",
             model="m-old", outcome="no_working_action", repair_rounds="2",
             forge_tool_errors="9", wall_s="900"),
    ]
    md = results_md.render(rows)
    assert "**2** runs · **1** verified" in md
    assert "`m-new`" in md and "`m-old`" in md
    assert "✅ verified" in md and "❌ no action" in md
    assert "4.0 min" in md          # 240 s median for the verified run
    assert "a.test" in md and "www.a.test" not in md


def test_main_writes_file(tmp_path):
    csv_path = tmp_path / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerow(_row(timestamp="t", site="https://x.test", model="m",
                        outcome="verified", wall_s="60"))
    out = tmp_path / "RESULTS.md"
    sys.argv = ["results_md.py", "--csv", str(csv_path), "--out", str(out)]
    results_md.main()
    assert "**1** runs" in out.read_text(encoding="utf-8")
