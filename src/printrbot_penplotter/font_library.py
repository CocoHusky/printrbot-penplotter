"""Discover installed typefaces that can be converted to plotter centerlines.

The project does not bundle commercial fonts.  Instead, the typed-font mode
uses fonts installed on the host machine and converts their filled glyphs to
single-line centerline paths.  This keeps the application license-safe while
still making common Word-style typefaces available on each user's computer.
"""

from __future__ import annotations

from pathlib import Path
import string


COMMON_FONT_FAMILIES = (
    "Arial",
    "Arial Narrow",
    "Avenir",
    "Avenir Next",
    "Baskerville",
    "Calibri",
    "Cambria",
    "Charter",
    "Comic Sans MS",
    "Courier",
    "Courier New",
    "DejaVu Sans",
    "DejaVu Serif",
    "DIN Alternate",
    "Futura",
    "Georgia",
    "Gill Sans",
    "Helvetica",
    "Helvetica Neue",
    "Liberation Sans",
    "Liberation Serif",
    "Menlo",
    "Monaco",
    "New York",
    "Noto Sans",
    "Noto Serif",
    "Optima",
    "Palatino",
    "PT Sans",
    "PT Serif",
    "Rockwell",
    "Seravek",
    "Times New Roman",
    "Trebuchet MS",
    "Verdana",
    "American Typewriter",
    "Bradley Hand",
    "Chalkboard SE",
    "Marker Felt",
    "Noteworthy",
    "PingFang SC",
    "Hiragino Sans GB",
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
)

# Matplotlib does not always index the macOS aliases used by the UI.
FONT_ALIASES = {
    "PingFang SC": "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "Noto Sans CJK SC": "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "Hiragino Sans GB": "/System/Library/Fonts/Hiragino Sans GB.ttc",
}

# The typeface picker is for notes, not every symbol font installed on macOS.
# Keep the characters most likely to occur in a note so a selected family
# cannot fail later on ordinary punctuation or numbers.
NOTE_CHARACTERS = frozenset(
    string.ascii_letters
    + string.digits
    + " .,!?;:'\"()-—’"
)


def resolve_font_family(family: str) -> str | None:
    """Return an installed font path for ``family`` without fallback."""

    from matplotlib.font_manager import FontProperties, findfont

    alias = FONT_ALIASES.get(family)
    if alias and Path(alias).is_file():
        return alias
    try:
        path = findfont(FontProperties(family=family), fallback_to_default=False)
    except (OSError, ValueError):
        return None
    return path if Path(path).is_file() else None


def supports_note_characters(font_path: str) -> bool:
    """Return whether a font can draw the normal characters used in notes."""

    from matplotlib.ft2font import FT2Font

    try:
        charmap = FT2Font(font_path).get_charmap()
    except Exception:
        return False
    return all(ord(character) in charmap for character in NOTE_CHARACTERS)


def installed_font_families() -> tuple[str, ...]:
    """Return unique family names known to the local Matplotlib font index."""

    # Only expose curated, note-friendly families. The previous long tail of
    # every installed family included symbol fonts such as Noto Sans Linear B,
    # which cannot draw ordinary punctuation and digits.
    return tuple(
        family
        for family in COMMON_FONT_FAMILIES
        if (path := resolve_font_family(family)) is not None
        and supports_note_characters(path)
    )


def font_library_entries() -> list[dict[str, str]]:
    """Return UI-safe font entries; filesystem paths are intentionally hidden."""

    entries: list[dict[str, str]] = []
    for family in installed_font_families():
        if family in COMMON_FONT_FAMILIES:
            description = "Common typeface; converted to plotter centerlines."
        else:
            description = "Installed typeface; converted to plotter centerlines."
        entries.append({"name": family, "description": description})
    return entries
