from __future__ import annotations

from enum import StrEnum


class TokenKind(StrEnum):
    EOF = "EOF"
    IDENT = "IDENT"
    INT_LITERAL = "INT_LITERAL"
    FLOAT_LITERAL = "FLOAT_LITERAL"
    CHAR_LITERAL = "CHAR_LITERAL"
    STRING_LITERAL = "STRING_LITERAL"

    KW_AUTO = "KW_AUTO"
    KW_BREAK = "KW_BREAK"
    KW_CASE = "KW_CASE"
    KW_CONST = "KW_CONST"
    KW_CONTINUE = "KW_CONTINUE"
    KW_DEFAULT = "KW_DEFAULT"
    KW_DO = "KW_DO"
    KW_ELSE = "KW_ELSE"
    KW_ENUM = "KW_ENUM"
    KW_EXTERN = "KW_EXTERN"
    KW_FOR = "KW_FOR"
    KW_GOTO = "KW_GOTO"
    KW_IF = "KW_IF"
    KW_INLINE = "KW_INLINE"
    KW_REGISTER = "KW_REGISTER"
    KW_RESTRICT = "KW_RESTRICT"
    KW_RETURN = "KW_RETURN"
    KW_SIZEOF = "KW_SIZEOF"
    KW_STATIC = "KW_STATIC"
    KW_STRUCT = "KW_STRUCT"
    KW_SWITCH = "KW_SWITCH"
    KW_TYPEDEF = "KW_TYPEDEF"
    KW_UNION = "KW_UNION"
    KW_VOLATILE = "KW_VOLATILE"
    KW_WHILE = "KW_WHILE"

    KW_BOOL = "KW_BOOL"
    KW_CHAR = "KW_CHAR"
    KW_DOUBLE = "KW_DOUBLE"
    KW_FLOAT = "KW_FLOAT"
    KW_INT = "KW_INT"
    KW_LONG = "KW_LONG"
    KW_SHORT = "KW_SHORT"
    KW_SIGNED = "KW_SIGNED"
    KW_UNSIGNED = "KW_UNSIGNED"
    KW_VOID = "KW_VOID"
    KW_COMPLEX = "KW_COMPLEX"
    KW_IMAGINARY = "KW_IMAGINARY"

    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COMMA = "COMMA"
    SEMI = "SEMI"
    COLON = "COLON"
    QUESTION = "QUESTION"
    DOT = "DOT"
    ARROW = "ARROW"
    ELLIPSIS = "ELLIPSIS"

    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"
    PERCENT = "PERCENT"
    AMP = "AMP"
    PIPE = "PIPE"
    CARET = "CARET"
    TILDE = "TILDE"
    BANG = "BANG"

    PLUS_PLUS = "PLUS_PLUS"
    MINUS_MINUS = "MINUS_MINUS"
    LSHIFT = "LSHIFT"
    RSHIFT = "RSHIFT"

    LT = "LT"
    GT = "GT"
    LE = "LE"
    GE = "GE"
    EQ = "EQ"
    NE = "NE"
    AND_AND = "AND_AND"
    OR_OR = "OR_OR"

    ASSIGN = "ASSIGN"
    PLUS_ASSIGN = "PLUS_ASSIGN"
    MINUS_ASSIGN = "MINUS_ASSIGN"
    STAR_ASSIGN = "STAR_ASSIGN"
    SLASH_ASSIGN = "SLASH_ASSIGN"
    PERCENT_ASSIGN = "PERCENT_ASSIGN"
    AMP_ASSIGN = "AMP_ASSIGN"
    PIPE_ASSIGN = "PIPE_ASSIGN"
    CARET_ASSIGN = "CARET_ASSIGN"
    LSHIFT_ASSIGN = "LSHIFT_ASSIGN"
    RSHIFT_ASSIGN = "RSHIFT_ASSIGN"


KEYWORDS: dict[str, TokenKind] = {
    "auto": TokenKind.KW_AUTO,
    "break": TokenKind.KW_BREAK,
    "case": TokenKind.KW_CASE,
    "char": TokenKind.KW_CHAR,
    "const": TokenKind.KW_CONST,
    "continue": TokenKind.KW_CONTINUE,
    "default": TokenKind.KW_DEFAULT,
    "do": TokenKind.KW_DO,
    "double": TokenKind.KW_DOUBLE,
    "else": TokenKind.KW_ELSE,
    "enum": TokenKind.KW_ENUM,
    "extern": TokenKind.KW_EXTERN,
    "float": TokenKind.KW_FLOAT,
    "for": TokenKind.KW_FOR,
    "goto": TokenKind.KW_GOTO,
    "if": TokenKind.KW_IF,
    "inline": TokenKind.KW_INLINE,
    "int": TokenKind.KW_INT,
    "long": TokenKind.KW_LONG,
    "register": TokenKind.KW_REGISTER,
    "restrict": TokenKind.KW_RESTRICT,
    "return": TokenKind.KW_RETURN,
    "short": TokenKind.KW_SHORT,
    "signed": TokenKind.KW_SIGNED,
    "sizeof": TokenKind.KW_SIZEOF,
    "static": TokenKind.KW_STATIC,
    "struct": TokenKind.KW_STRUCT,
    "switch": TokenKind.KW_SWITCH,
    "typedef": TokenKind.KW_TYPEDEF,
    "union": TokenKind.KW_UNION,
    "unsigned": TokenKind.KW_UNSIGNED,
    "void": TokenKind.KW_VOID,
    "volatile": TokenKind.KW_VOLATILE,
    "while": TokenKind.KW_WHILE,
    "_Bool": TokenKind.KW_BOOL,
    "_Complex": TokenKind.KW_COMPLEX,
    "_Imaginary": TokenKind.KW_IMAGINARY,
}

PUNCTUATORS: dict[str, TokenKind] = {
    "{": TokenKind.LBRACE,
    "}": TokenKind.RBRACE,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    ",": TokenKind.COMMA,
    ";": TokenKind.SEMI,
    ":": TokenKind.COLON,
    "?": TokenKind.QUESTION,
    ".": TokenKind.DOT,
    "->": TokenKind.ARROW,
    "...": TokenKind.ELLIPSIS,
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "%": TokenKind.PERCENT,
    "&": TokenKind.AMP,
    "|": TokenKind.PIPE,
    "^": TokenKind.CARET,
    "~": TokenKind.TILDE,
    "!": TokenKind.BANG,
    "++": TokenKind.PLUS_PLUS,
    "--": TokenKind.MINUS_MINUS,
    "<<": TokenKind.LSHIFT,
    ">>": TokenKind.RSHIFT,
    "<": TokenKind.LT,
    ">": TokenKind.GT,
    "<=": TokenKind.LE,
    ">=": TokenKind.GE,
    "==": TokenKind.EQ,
    "!=": TokenKind.NE,
    "&&": TokenKind.AND_AND,
    "||": TokenKind.OR_OR,
    "=": TokenKind.ASSIGN,
    "+=": TokenKind.PLUS_ASSIGN,
    "-=": TokenKind.MINUS_ASSIGN,
    "*=": TokenKind.STAR_ASSIGN,
    "/=": TokenKind.SLASH_ASSIGN,
    "%=": TokenKind.PERCENT_ASSIGN,
    "&=": TokenKind.AMP_ASSIGN,
    "|=": TokenKind.PIPE_ASSIGN,
    "^=": TokenKind.CARET_ASSIGN,
    "<<=": TokenKind.LSHIFT_ASSIGN,
    ">>=": TokenKind.RSHIFT_ASSIGN,
}
