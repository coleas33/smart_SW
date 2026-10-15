"""Remove local folder names from benchmark messages before they are recorded."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from swreview.benchmark.sets import REPO_ROOT


def one_line(value: object, *, preserve_spacing: bool = False) -> str:
    """Flatten messages, preserving path spacing until local paths have been scrubbed."""
    text = str(value)
    return " ".join(text.splitlines() if preserve_spacing else text.split())


def without_local_paths(
    text: str, *, run_dir: Path | str, root: Path | str = REPO_ROOT
) -> str:
    """Replace local folders, as spelled and resolved, longest first in any path spelling."""
    folders: dict[str, str] = {}
    known = [
        (Path(run_dir), "<run>"),
        (Path(root), "<repo>"),
        (Path(tempfile.gettempdir()), "<tmp>"),
    ]
    try:
        known.append((Path.home(), "<home>"))
    except RuntimeError:
        pass  # an account with no home folder has none to scrub (owner decisions 92A, 104A)
    for folder, replacement in known:
        for form in (folder, folder.resolve()):
            if form.parent != form:
                folders.setdefault(str(form), replacement)

    for folder, replacement in sorted(folders.items(), key=lambda item: len(item[0]), reverse=True):
        forward = folder.replace("\\", "/")
        backward = forward.replace("/", "\\")
        spellings = (forward, backward, backward.replace("\\", "\\\\"))
        pattern = "(?:" + "|".join(re.escape(spelling) for spelling in spellings) + r")(?![\w-])"
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text
