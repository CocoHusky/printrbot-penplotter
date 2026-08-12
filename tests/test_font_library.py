from printrbot_penplotter.font_library import (
    COMMON_FONT_FAMILIES,
    font_library_entries,
    resolve_font_family,
)


def test_missing_font_does_not_fall_back_to_a_different_family() -> None:
    assert resolve_font_family("This Typeface Does Not Exist") is None


def test_font_library_has_unique_names_and_no_paths() -> None:
    entries = font_library_entries()
    names = [entry["name"] for entry in entries]
    assert names == list(dict.fromkeys(names))
    assert entries
    assert all("/" not in entry["name"] for entry in entries)


def test_curated_families_are_listed_before_the_long_tail() -> None:
    names = [entry["name"] for entry in font_library_entries()]
    installed_curated = [
        family for family in COMMON_FONT_FAMILIES if resolve_font_family(family)
    ]
    assert names[: len(installed_curated)] == installed_curated


def test_library_includes_more_display_and_handwriting_choices() -> None:
    expected_choices = {
        "Avenir",
        "Baskerville",
        "Futura",
        "Gill Sans",
        "Menlo",
        "Optima",
        "PT Sans",
        "Rockwell",
    }
    assert expected_choices <= set(COMMON_FONT_FAMILIES)
