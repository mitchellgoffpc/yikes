from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.normalize import normalize
from yikes.parse.parse import parse


def _bt(name: str) -> AST.BuiltinType:
    return AST.BuiltinType(name)

def _block(items: list[AST.Stmt]) -> AST.Block:
    return AST.Block(items, scope=AST.Scope())

def _ts(name: str) -> AST.TypeSpec:
    return AST.TypeSpec(_bt(name))

def _decl(name: str, *, suffixes: list[AST.DirectSuffix] | None = None) -> AST.Declarator:
    return AST.Declarator(None, AST.DirectDeclarator(name, None, suffixes or []))

def _init(name: str, init: AST.Initializer | None = None, *, suffixes: list[AST.DirectSuffix] | None = None) -> AST.InitDeclarator:
    return AST.InitDeclarator(_decl(name, suffixes=suffixes), init)

def _array_suffix(size: AST.Expr | None) -> AST.DirectSuffix:
    return AST.DirectSuffix(None, size, False, False)

def _stmt(source: str) -> AST.Stmt:
    program = normalize(parse(f"int main() {{ {source} }}"))
    item = program.items[0]
    assert isinstance(item, AST.FunctionDef)
    return item.body.items[0]

def _block_items(source: str) -> list[AST.Stmt]:
    program = normalize(parse(f"int main() {{ {source} }}"))
    item = program.items[0]
    assert isinstance(item, AST.FunctionDef)
    return item.body.items


def test_normalize_for_loops(subtests: pytest.Subtests) -> None:
    cases = [
        ("for (;;) x;",
         AST.While(AST.BoolLiteral(True), _block([AST.ExprStmt(AST.Identifier("x"))]))),
        ("for (i = 0; i < 3; i = i + 1) x;",
         _block([
             AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.IntLiteral(0))),
             AST.While(
                 AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
                 _block([
                     AST.ExprStmt(AST.Identifier("x")),
                     AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.Binary("+", AST.Identifier("i"), AST.IntLiteral(1)))),
                 ]),
             ),
         ])),
        ("for (int i = 0; i < 3; i = i + 1) { x; }",
         _block([
             AST.VarDecl("i", _bt("int"), AST.IntLiteral(0)),
             AST.While(
                 AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
                 _block([
                     AST.ExprStmt(AST.Identifier("x")),
                     AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.Binary("+", AST.Identifier("i"), AST.IntLiteral(1)))),
                 ]),
             ),
         ])),
        ("for (int i = 0, j = 1; i < 3; i = i + 1) x;",
         _block([
             AST.Declaration([_ts("int")], [_init("i", AST.IntLiteral(0))]),
             AST.Declaration([_ts("int")], [_init("j", AST.IntLiteral(1))]),
             AST.While(
                 AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
                 _block([
                     AST.ExprStmt(AST.Identifier("x")),
                     AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.Binary("+", AST.Identifier("i"), AST.IntLiteral(1)))),
                 ]),
             ),
         ])),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _stmt(source) == expected


def test_normalize_do_while(subtests: pytest.Subtests) -> None:
    cases = [
        ("do x; while (y);",
         AST.While(
             AST.BoolLiteral(True),
             _block([
                 AST.ExprStmt(AST.Identifier("x")),
                 AST.If(AST.Unary("!", AST.Identifier("y")), AST.Break(), None),
             ]),
         )),
        ("do { x; y; } while (cond);",
         AST.While(
             AST.BoolLiteral(True),
             _block([
                 AST.ExprStmt(AST.Identifier("x")),
                 AST.ExprStmt(AST.Identifier("y")),
                 AST.If(AST.Unary("!", AST.Identifier("cond")), AST.Break(), None),
             ]),
         )),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _stmt(source) == expected


def test_normalize_declaration_lists(subtests: pytest.Subtests) -> None:
    cases = [
        ("int a, b;",
         [
             AST.Declaration([_ts("int")], [_init("a")]),
             AST.Declaration([_ts("int")], [_init("b")]),
         ]),
        ("int a = 1, b = 2;",
         [
             AST.Declaration([_ts("int")], [_init("a", AST.IntLiteral(1))]),
             AST.Declaration([_ts("int")], [_init("b", AST.IntLiteral(2))]),
         ]),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _block_items(source) == expected


def test_normalize_array_subscript(subtests: pytest.Subtests) -> None:
    cases = [
        ("a[2];", AST.ExprStmt(AST.Unary("*", AST.Binary("+", AST.Identifier("a"), AST.IntLiteral(2))))),
        ("p[i + 1];",
         AST.ExprStmt(AST.Unary("*", AST.Binary("+", AST.Identifier("p"), AST.Binary("+", AST.Identifier("i"), AST.IntLiteral(1)))))),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _stmt(source) == expected


def test_normalize_array_declaration(subtests: pytest.Subtests) -> None:
    cases = [
        ("int a[2];",
         [
             AST.VarDecl("a", AST.ArrayType(_bt("int"), AST.IntLiteral(2)), None),
         ]),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _block_items(source) == expected


def test_normalize_block_bodies(subtests: pytest.Subtests) -> None:
    cases = [
        ("if (x) y;",
         AST.If(AST.Identifier("x"), _block([AST.ExprStmt(AST.Identifier("y"))]), None)),
        ("if (x) y; else z;",
         AST.If(AST.Identifier("x"), _block([AST.ExprStmt(AST.Identifier("y"))]), _block([AST.ExprStmt(AST.Identifier("z"))]))),
        ("while (x) y;",
         AST.While(AST.Identifier("x"), _block([AST.ExprStmt(AST.Identifier("y"))]))),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _stmt(source) == expected
