"""Minimal S-expression parser for KiCad board files.

Returns plain nested lists of strings; callers convert numbers as needed.
Quoted and unquoted atoms parse to equal strings, but quoted ones are marked
with :class:`QuotedStr` — KiCad 10 stores a pad/segment net as ``(net "NAME")``
while KiCad <= 9 stores ``(net 42 "NAME")``, and the quoting distinction lets
callers tell a net *name* that happens to look numeric apart from a net *id*.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(
    r"""
    (?P<lparen>\() |
    (?P<rparen>\)) |
    (?P<quoted>"(?:\\.|[^"\\])*") |
    (?P<atom>[^\s()"]+)
    """,
    re.VERBOSE | re.DOTALL,
)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


class QuotedStr(str):
    """An atom that was written as a quoted string in the source."""

    __slots__ = ()


def _unquote(token: str) -> str:
    body = token[1:-1]
    return re.sub(
        r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), body
    )


def parse(text: str) -> list:
    """Parse S-expression source into a list of top-level forms."""
    stack: list[list] = [[]]
    for match in _TOKEN_RE.finditer(text):
        kind = match.lastgroup
        if kind == "lparen":
            new: list = []
            stack[-1].append(new)
            stack.append(new)
        elif kind == "rparen":
            if len(stack) == 1:
                raise ValueError(f"unbalanced ')' at offset {match.start()}")
            stack.pop()
        elif kind == "quoted":
            stack[-1].append(QuotedStr(_unquote(match.group(0))))
        else:
            stack[-1].append(match.group(0))
    if len(stack) != 1:
        raise ValueError("unbalanced '(': unexpected end of input")
    return stack[0]
