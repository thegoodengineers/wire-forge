"""Web API: the tally only reflects results.csv, and starting a run is guarded."""

import csv
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WIREFORGE_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("WIREFORGE_RESULTS_CSV", str(tmp_path / "results.csv"))
    monkeypatch.setenv("WIREFORGE_PASSCODE", "letmein")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Never read the developer's .env here: a real key would let this test start a paid run.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    import wireforge.config, wireforge.pipeline, wireforge.web.server as server
    importlib.reload(wireforge.config)
    importlib.reload(wireforge.pipeline)
    importlib.reload(server)
    return TestClient(server.app), tmp_path


def test_pages_and_empty_tally(client):
    c, _ = client
    assert "Wire Forge" in c.get("/").text
    t = c.get("/api/tally").json()
    assert t["runs"] == 0 and t["median_min"] is None
    assert c.get("/api/runs").json() == []


def test_tally_comes_from_results_csv(client):
    c, tmp = client
    from wireforge.pipeline import CSV_FIELDS
    with (tmp / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", *CSV_FIELDS])
        w.writeheader()
        w.writerow({"site": "https://a.test", "model": "m1", "outcome": "verified", "type": "write", "wall_s": "120", "repair_rounds": "1"})
        w.writerow({"site": "https://b.test", "model": "m2", "outcome": "rejected_by_verifier", "type": "read", "wall_s": "300", "repair_rounds": "2"})
    t = c.get("/api/tally").json()
    assert (t["runs"], t["verified"], t["write_actions"], t["median_min"]) == (2, 1, 1, 2.0)
    assert t["models"]["m2"]["verified"] == 0


def test_start_run_is_guarded(client):
    c, _ = client
    body = {"url": "https://a.test", "goal": "find things", "passcode": "nope"}
    assert c.post("/api/runs", json=body).status_code == 403
    assert c.post("/api/runs", json={**body, "passcode": "letmein", "model": "gpt"}).status_code == 400
    assert c.post("/api/runs", json={**body, "passcode": "letmein"}).status_code == 503  # no API key
    assert c.post("/api/runs", json={**body, "url": "file:///etc/passwd", "passcode": "letmein"}).status_code == 422


def test_run_ids_cannot_escape_out_dir(client):
    c, _ = client
    assert c.get("/api/runs/..%2F..%2Fetc").status_code == 404
    assert c.get("/api/runs/nope").status_code == 404


def test_cancel_run_is_guarded(client):
    c, _ = client
    assert c.post("/api/runs/nope/cancel", json={"passcode": "bad"}).status_code == 403
    assert c.post("/api/runs/nope/cancel", json={"passcode": "letmein"}).status_code == 409
