from pathlib import Path
from printrbot_penplotter.handwriting_packs import HandwritingPackStore


def _font() -> dict[str, object]:
    variant = {"strokes": [[[0.0,0.0],[0.5,1.0],[1.0,0.0]]], "advance": 1.1, "entry": [0.0,0.0], "exit": [1.0,0.0], "label": "base"}
    fallback = {"strokes": [[[0.0,1.0],[0.5,0.5],[0.5,0.2]], [[0.5,0.05],[0.5,0.0]]], "advance": 0.8, "label": "base"}
    return {"name":"My Hand","fallback":"?","glyphs":{"A":[variant],"?":[fallback]}}


def test_install_and_list_handwriting_pack(tmp_path: Path) -> None:
    store = HandwritingPackStore(tmp_path)
    installed = store.install("My Hand", _font())
    assert installed["font_name"] == "My Hand"
    assert installed["glyphs"] == 2
    packs = store.list()
    assert len(packs) == 1
    assert packs[0]["font_name"] == "My Hand"
