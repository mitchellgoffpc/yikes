from __future__ import annotations

from typing import NamedTuple

from yikes.lex.tokens import KEYWORDS, PUNCTUATORS, TokenKind


class Token(NamedTuple):
    kind: TokenKind
    value: str | int | float | None
    line: int
    col: int


_PUNCTUATOR_LIST: list[str] = list(PUNCTUATORS.keys())
_PUNCTUATOR_LIST.sort(key=len, reverse=True)


def lex(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(source)

    def error(message: str) -> None:
        raise ValueError(f"{message} at {line}:{col}")

    def peek(offset: int = 0) -> str:
        pos = i + offset
        return source[pos] if pos < n else ""

    def advance(count: int = 1) -> str:
        nonlocal i, line, col
        text = source[i : i + count]
        for ch in text:
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
        i += count
        return text

    def match(text: str) -> bool:
        return source.startswith(text, i)

    def skip_whitespace() -> None:
        nonlocal i
        while i < n:
            ch = peek()
            if ch in " \t\n":
                advance()
                continue
            if ch == "\r":
                advance()
                if peek() == "\n":
                    advance()
                continue
            if match("//"):
                while i < n and peek() not in "\r\n":
                    advance()
                continue
            if match("/*"):
                advance(2)
                while i < n and not match("*/"):
                    advance()
                if not match("*/"):
                    error("Unterminated block comment")
                advance(2)
                continue
            break

    def read_identifier() -> Token:
        start_col = col
        start_i = i
        advance()
        while peek().isalnum() or peek() == "_":
            advance()
        text = source[start_i:i]
        kind = KEYWORDS.get(text, TokenKind.IDENT)
        value = text if kind == TokenKind.IDENT else None
        return Token(kind, value, line, start_col)

    def read_number() -> Token:
        start_col = col
        start_i = i
        saw_dot = False
        saw_exp = False

        if peek() == ".":
            saw_dot = True
            advance()
        while peek().isdigit():
            advance()
        if peek() == ".":
            if saw_dot:
                error("Malformed number")
            saw_dot = True
            advance()
            while peek().isdigit():
                advance()
        ch = peek()
        if ch and ch in "eE":
            saw_exp = True
            advance()
            ch = peek()
            if ch and ch in "+-":
                advance()
            if not peek().isdigit():
                error("Malformed exponent")
            while peek().isdigit():
                advance()

        text = source[start_i:i]
        if saw_dot or saw_exp:
            return Token(TokenKind.FLOAT_LITERAL, float(text), line, start_col)
        return Token(TokenKind.INT_LITERAL, int(text), line, start_col)

    def read_string(quote: str) -> Token:
        start_col = col
        advance()
        chars: list[str] = []
        while i < n:
            ch = peek()
            if ch == quote:
                advance()
                break
            if ch in "\r\n":
                error("Unterminated string literal")
            if ch == "\\":
                advance()
                esc = peek()
                if not esc:
                    error("Unterminated string literal")
                mapping = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", "'": "'", '"': '"'}
                chars.append(mapping.get(esc, esc))
                advance()
                continue
            chars.append(ch)
            advance()
        else:
            error("Unterminated string literal")

        value = "".join(chars)
        kind = TokenKind.CHAR_LITERAL if quote == "'" else TokenKind.STRING_LITERAL
        return Token(kind, value, line, start_col)

    while i < n:
        skip_whitespace()
        if i >= n:
            break
        ch = peek()

        if ch.isalpha() or ch == "_":
            tokens.append(read_identifier())
            continue
        if ch.isdigit() or (ch == "." and peek(1).isdigit()):
            tokens.append(read_number())
            continue
        if ch == "'" or ch == '"':
            tokens.append(read_string(ch))
            continue

        for punct in _PUNCTUATOR_LIST:
            if match(punct):
                tokens.append(Token(PUNCTUATORS[punct], None, line, col))
                advance(len(punct))
                break
        else:
            error(f"Unexpected character {ch!r}")

    tokens.append(Token(TokenKind.EOF, None, line, col))
    return tokens

