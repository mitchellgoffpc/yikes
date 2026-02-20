from __future__ import annotations

import pytest

from yikes.lex.lex import lex
from yikes.lex.tokens import TokenKind


def _simplify(tokens: list) -> list[tuple[TokenKind, object | None]]:
    return [(token.kind, token.value) for token in tokens]


def test_identifiers_and_keywords(subtests: pytest.Subtests) -> None:
    cases = [
        ("foo bar", [(TokenKind.IDENT, "foo"), (TokenKind.IDENT, "bar"), (TokenKind.EOF, None)]),
        ("int x;", [(TokenKind.KW_INT, None), (TokenKind.IDENT, "x"), (TokenKind.SEMI, None), (TokenKind.EOF, None)]),
        ("_Bool ok", [(TokenKind.KW_BOOL, None), (TokenKind.IDENT, "ok"), (TokenKind.EOF, None)]),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _simplify(lex(source)) == expected


def test_numbers(subtests: pytest.Subtests) -> None:
    cases = [
        ("0 42", [(TokenKind.INT_LITERAL, 0), (TokenKind.INT_LITERAL, 42), (TokenKind.EOF, None)]),
        ("3.14 .5 2.", [(TokenKind.FLOAT_LITERAL, 3.14), (TokenKind.FLOAT_LITERAL, 0.5), (TokenKind.FLOAT_LITERAL, 2.0), (TokenKind.EOF, None)]),
        ("1e3 2E-2", [(TokenKind.FLOAT_LITERAL, 1000.0), (TokenKind.FLOAT_LITERAL, 0.02), (TokenKind.EOF, None)]),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _simplify(lex(source)) == expected


def test_strings_and_chars(subtests: pytest.Subtests) -> None:
    cases = [
        ("'a' \"hi\"", [(TokenKind.CHAR_LITERAL, "a"), (TokenKind.STRING_LITERAL, "hi"), (TokenKind.EOF, None)]),
        ("'\\n' \"a\\t\"",
         [(TokenKind.CHAR_LITERAL, "\n"), (TokenKind.STRING_LITERAL, "a\t"), (TokenKind.EOF, None)]),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _simplify(lex(source)) == expected


def test_punctuators_and_operators(subtests: pytest.Subtests) -> None:
    cases = [
        ("+-*/",
         [(TokenKind.PLUS, None), (TokenKind.MINUS, None), (TokenKind.STAR, None), (TokenKind.SLASH, None), (TokenKind.EOF, None)]),
        ("== != <= >= && ||",
         [(TokenKind.EQ, None), (TokenKind.NE, None), (TokenKind.LE, None), (TokenKind.GE, None),
          (TokenKind.AND_AND, None), (TokenKind.OR_OR, None), (TokenKind.EOF, None)]),
        ("<<= >>= ++ --",
         [(TokenKind.LSHIFT_ASSIGN, None), (TokenKind.RSHIFT_ASSIGN, None), (TokenKind.PLUS_PLUS, None), (TokenKind.MINUS_MINUS, None), (TokenKind.EOF, None)]),
        ("a->b ...",
         [(TokenKind.IDENT, "a"), (TokenKind.ARROW, None), (TokenKind.IDENT, "b"), (TokenKind.ELLIPSIS, None), (TokenKind.EOF, None)]),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _simplify(lex(source)) == expected


def test_comments_and_whitespace(subtests: pytest.Subtests) -> None:
    cases = [
        ("a // comment\nb", [(TokenKind.IDENT, "a"), (TokenKind.IDENT, "b"), (TokenKind.EOF, None)]),
        ("a/*x*/b", [(TokenKind.IDENT, "a"), (TokenKind.IDENT, "b"), (TokenKind.EOF, None)]),
        ("a\r\nb", [(TokenKind.IDENT, "a"), (TokenKind.IDENT, "b"), (TokenKind.EOF, None)]),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _simplify(lex(source)) == expected


def test_errors(subtests: pytest.Subtests) -> None:
    cases = [
        ("@", "Unexpected character"),
        ("'unterminated", "Unterminated string literal"),
        ("\"unterminated", "Unterminated string literal"),
        ("1e+", "Malformed exponent"),
        ("/* unterminated", "Unterminated block comment"),
    ]

    for source, match in cases:
        with subtests.test(source=source), pytest.raises(ValueError, match=match):
            lex(source)
