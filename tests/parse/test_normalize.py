from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.normalize import normalize
from yikes.parse.parse import parse


def _bt(name: str) -> AST.BuiltinType:
    return AST.BuiltinType(name)

def _stmt(source: str) -> AST.Stmt:
    program = normalize(parse(f"int main() {{ {source} }}"))
    item = program.items[0]
    assert isinstance(item, AST.FunctionDef)
    return item.body.items[0]


def test_normalize_for_loops(subtests: pytest.Subtests) -> None:
    cases = [
        ("for (;;) x;",
         AST.While(AST.BoolLiteral(True), AST.Block([AST.ExprStmt(AST.Identifier("x"))]))),
        ("for (i = 0; i < 3; i = i + 1) x;",
         AST.Block([
             AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.IntLiteral(0))),
             AST.While(
                 AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
                 AST.Block([
                     AST.ExprStmt(AST.Identifier("x")),
                     AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.Binary("+", AST.Identifier("i"), AST.IntLiteral(1)))),
                 ]),
             ),
         ])),
        ("for (int i = 0; i < 3; i = i + 1) { x; }",
         AST.Block([
             AST.VarDecl("i", _bt("int"), AST.IntLiteral(0)),
             AST.While(
                 AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
                 AST.Block([
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
             AST.Block([
                 AST.ExprStmt(AST.Identifier("x")),
                 AST.If(AST.Unary("!", AST.Identifier("y")), AST.Break(), None),
             ]),
         )),
        ("do { x; y; } while (cond);",
         AST.While(
             AST.BoolLiteral(True),
             AST.Block([
                 AST.ExprStmt(AST.Identifier("x")),
                 AST.ExprStmt(AST.Identifier("y")),
                 AST.If(AST.Unary("!", AST.Identifier("cond")), AST.Break(), None),
             ]),
         )),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _stmt(source) == expected
