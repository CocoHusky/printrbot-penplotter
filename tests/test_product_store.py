from pathlib import Path
from printrbot_penplotter.product_store import ProductStore


def test_profiles_round_trip(tmp_path: Path) -> None:
    store = ProductStore(tmp_path)
    saved = store.save_profile("pen", "Fine liner", {"tip_mm": 0.4, "z_up_mm": 5.0})
    assert saved["name"] == "Fine liner"
    profiles = store.list_profiles("pen")
    assert profiles["profiles"]["pen"]["Fine liner"]["values"]["tip_mm"] == 0.4


def test_job_history_is_content_addressed_and_queueable(tmp_path: Path) -> None:
    store = ProductStore(tmp_path)
    first = store.record_job(metadata={"style": "crosshatch"}, gcode="G21\nG90\n", preview_svg="<svg/>")
    second = store.record_job(metadata={"style": "crosshatch"}, gcode="G21\nG90\n", preview_svg="<svg/>")
    assert first["id"] == second["id"]
    assert len(store.list_jobs()) == 1
    queue = store.queue_job(str(first["id"]))
    assert queue == [first["id"]]
    assert store.dequeue_job(str(first["id"])) == []
