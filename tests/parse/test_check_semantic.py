from __future__ import annotations

import pytest

from yikes.parse.bind import bind
from yikes.parse.check_semantic import check_semantic
from yikes.parse.check_types import check_types
from yikes.parse.parse import parse
from yikes.parse.resolve_types import resolve_types


def _semantic_program(source: str) -> None:
    check_semantic(check_types(resolve_types(bind(parse(source)))))

def test_control_flow_errors(subtests: pytest.Subtests) -> None:
    cases = [
        ("int f() { break; }", r"break not within loop or switch at \d+:\d+"),
        ("int f() { continue; }", r"continue not within loop at \d+:\d+"),
        ("int f() { case 1: break; }", r"case not within switch at \d+:\d+"),
        ("int f() { default: break; }", r"default not within switch at \d+:\d+"),
        ("int f() { int x = 1; switch (1) { case x: break; } }", r"case value is not an integer constant expression at \d+:\d+"),
        ("int f() { switch (1) { case 1: break; case 1: break; } }", r"duplicate case value at \d+:\d+"),
        ("int f() { switch (1) { default: break; default: break; } }", r"duplicate default label at \d+:\d+"),
        ("int f() { goto missing; }", r"Unknown label 'missing' at \d+:\d+"),
    ]
    for source, error_match in cases:
        with subtests.test(source=source), pytest.raises(ValueError, match=error_match):
            _semantic_program(source)
