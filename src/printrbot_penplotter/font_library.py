"""Discover installed typefaces that can be converted to plotter centerlines.

The project does not bundle commercial fonts.  Instead, the typed-font mode
uses fonts installed on the host machine and converts their filled glyphs to
single-line centerline paths.  This keeps the application license-safe while
still making common Word-style typefaces available on each user's computer.
"""

from __future__ import annotations

from pathlib import Path


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


def installed_font_families() -> tuple[str, ...]:
    """Return unique family names known to the local Matplotlib font index."""

    from matplotlib import font_manager

    families = {entry.name for entry in font_manager.fontManager.ttflist if entry.name}
    # Put familiar choices first, then expose the rest for users with larger
    # language/font installations.  The UI can therefore support more than a
    # hard-coded handful without shipping font files in the repository.
    preferred = [family for family in COMMON_FONT_FAMILIES if resolve_font_family(family)]
    remaining = sorted(families - set(preferred), key=str.casefold)
    return tuple(preferred + remaining)


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
