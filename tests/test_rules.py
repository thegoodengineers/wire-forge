"""Rules that decide what a run is allowed to claim."""

import json

from wireforge import config, pipeline
from wireforge.pipeline import CSV_FIELDS, recorded_type
from wireforge.verifier import Verifier


def test_write_counts_only_when_the_site_stored_it():
    assert recorded_type("write", {"passed": True, "write_persisted": True}) == "write"
    assert recorded_type("write", {"passed": True, "write_persisted": False}) == "read"
    assert recorded_type("write", {"passed": True}) == "read"
    assert recorded_type("read", {"passed": True}) == "read"


def _verifier(tmp_path, action_type):
    d = tmp_path / "action"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps({"action_id": "a_b", "type": action_type}))
    v = Verifier.__new__(Verifier)  # the submit rules need no browser or model
    v.spec, v.runs, v.verdict = json.loads((d / "spec.json").read_text()), 2, None
    v.agent = type("A", (), {"finished": False})()
    return v


def test_write_verdict_must_say_whether_the_change_was_stored(tmp_path):
    v = _verifier(tmp_path, "write")
    check = [{"what": "x", "action_value": "1", "page_value": "1", "match": True}]
    assert v.submit(True, check, "ok").startswith("Refused")
    assert v.verdict is None
    assert v.submit(True, check, "ok", write_persisted=False) == "Verdict recorded."
    assert v.verdict["write_persisted"] is False


def test_changed_columns_keep_the_old_csv_intact(tmp_path, monkeypatch):
    csv_path = tmp_path / "results.csv"
    csv_path.write_text("timestamp,site,outcome\n2026-09-26,https://a.test,verified\n", encoding="utf-8")
    monkeypatch.setattr(config, "RESULTS_CSV", csv_path)
    pipeline._append_csv({"site": "https://b.test", "outcome": "verified"})
    legacy = list(tmp_path.glob("results.legacy-*.csv"))
    assert len(legacy) == 1 and "https://a.test" in legacy[0].read_text(encoding="utf-8")
    assert csv_path.read_text(encoding="utf-8").splitlines()[0].split(",") == CSV_FIELDS


def test_binary_request_body_does_not_drop_the_entry():
    from wireforge.browser import BrowserSession

    class Req:
        post_data_buffer = b"\x1f\x8b\x08\x00binary"

        @property
        def post_data(self):
            raise UnicodeDecodeError("utf-8", b"\x8b", 0, 1, "invalid start byte")

    class TextReq:
        post_data, post_data_buffer = '{"q": 1}', b'{"q": 1}'

    assert BrowserSession._post_text(Req()) == "<binary body, 10 bytes>"
    assert BrowserSession._post_text(TextReq()) == '{"q": 1}'


def test_a_crashed_run_still_writes_a_row(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_CSV", tmp_path / "results.csv")
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")

    def boom(*a, **k):
        raise RuntimeError("Target page, context or browser has been closed")

    monkeypatch.setattr(pipeline, "_run", boom)
    row = pipeline.forge_action("https://a.test", "goal", "m1")
    assert row["outcome"] == "error" and row["emits"] == 0
    assert "error" in (tmp_path / "results.csv").read_text(encoding="utf-8")
