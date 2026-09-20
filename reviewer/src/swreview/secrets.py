"""Shared provider-key detectors and configured secret sources for audit and handoff."""

from __future__ import annotations

import os
import re

KEY_ENV_VARS: tuple[str, ...] = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
"""Every variable a provider key can be configured in - all of them, deliberately.

`ProviderSettings.from_env` resolves `GOOGLE_API_KEY` ahead of `GEMINI_API_KEY` because a
run needs exactly one key; an audit wants the opposite, so this list is not built from
that precedence. A key sitting in the variable the last run did not pick is still a key
that must not be in a file.
"""

KEY_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shape:openai-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("shape:google-key", re.compile(r"AIza[A-Za-z0-9_-]{35}")),
)
"""What a provider key looks like, for the run this command was made for.

On the workstation the key is DPAPI-protected under `%APPDATA%` and is decrypted into the
backend child's environment block only, so an audit started from a separate shell has no
key to search for and an environment-only scan would report "none" no matter what is in
the files. These two patterns are what carry the check there: `sk-` plus at least twenty
key characters covers both OpenAI key formats, and `AIza` plus thirty-five is the shape
Google issues. They are a safety net over the verbatim search, not a replacement for it -
a key from a settings file this shell cannot see has no verbatim value to match.
"""


def secret_env_names(bridge_secret_env: str | None) -> list[str]:
    """The variables this audit reads a secret from: the key ones, plus the bridge one.

    The bridge secret is named by its variable rather than passed as a value because a
    secret on a command line is visible in the process list.
    """
    names = [*KEY_ENV_VARS]
    if bridge_secret_env is not None and bridge_secret_env not in names:
        names.append(bridge_secret_env)
    return names


def configured_secrets(bridge_secret_env: str | None) -> list[tuple[str, str]]:
    """`(source, value)` for every secret this shell actually holds.

    A variable that is set but blank is not a secret - that is the common Windows case,
    and treating `""` as a value would both match every line of every file and make a
    vacuous run look armed.
    """
    found = []
    for name in secret_env_names(bridge_secret_env):
        value = os.environ.get(name, "").strip()
        if value:
            found.append((f"env:{name}", value))
    return found
