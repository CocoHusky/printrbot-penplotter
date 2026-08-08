from fastapi.testclient import TestClient
from printrbot_penplotter.studio_server import app


def test_product_profile_and_job_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PRINTRBOT_HOME", str(tmp_path))
    client = TestClient(app)
    response = client.post("/api/product/profiles", json={"kind":"pen","name":"0.5 fineliner","values":{"tip_mm":0.5}})
    assert response.status_code == 200
    response = client.get("/api/product/profiles?kind=pen")
    assert response.status_code == 200
    assert "0.5 fineliner" in response.json()["profiles"]["pen"]

    job = client.post("/api/product/jobs", json={"metadata":{"style":"clean_outline"},"gcode":"G21\nG90\n","preview_svg":"<svg/>"})
    assert job.status_code == 200
    job_id = job.json()["id"]
    queued = client.post("/api/product/queue", json={"job_id":job_id})
    assert queued.status_code == 200
    assert queued.json()["queue"] == [job_id]
