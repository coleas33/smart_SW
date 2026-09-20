"""Plain model-authored text rendered safely inside a Markdown paragraph."""

from html import escape


def markdown_text(text: str) -> str:
    """Keep explanation text literal: no links, HTML, emphasis, or code spans."""
    value = escape(text, quote=False)
    for character in "\\`*_{}[]()#!|":
        value = value.replace(character, "\\" + character)
    return value
