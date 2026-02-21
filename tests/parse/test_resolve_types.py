from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.bind import bind
from yikes.parse.parse import parse
from yikes.parse.resolve_types import resolve_types


def _resolve_program(source: str) -> AST.Program:
    program = bind(parse(source, with_spans=False))
    return resolve_types(program)

def _id(name: str) -> AST.Identifier:
    return AST.Identifier(name)

def _bt(name: str) -> AST.BuiltinType:
    return AST.BuiltinType([AST.TypeKeyword(name)])

def _ident(scope: AST.Scope, name: str) -> AST.Symbol:
    symbol = scope.idents.get(name)
    assert symbol is not None
    return symbol

def _tag(scope: AST.Scope, name: str) -> AST.Symbol:
    symbol = scope.tags.get(name)
    assert symbol is not None
    return symbol


def test_global_type_resolution(subtests: pytest.Subtests) -> None:
    cases = [
        ("typedef int T; T x;",
         {"idents": {"T": _bt("int"), "x": _bt("int")}, "tags": {}}),
        ("struct S { int x; }; struct S s;",
         {"idents": {"s": AST.StructType(_id("S"), [AST.Field(_id("x"), _bt("int"), None)])},
          "tags": {"S": AST.StructType(_id("S"), [AST.Field(_id("x"), _bt("int"), None)])}}),
        ("union U { int x; char y; }; union U u;",
         {"idents": {"u": AST.UnionType(_id("U"), [AST.Field(_id("x"), _bt("int"), None), AST.Field(_id("y"), _bt("char"), None)])},
          "tags": {"U": AST.UnionType(_id("U"), [AST.Field(_id("x"), _bt("int"), None), AST.Field(_id("y"), _bt("char"), None)])}}),
        ("enum E { A, B = 3 }; enum E e;",
         {"idents": {"e": AST.EnumType(_id("E"), [AST.Enumerator(_id("A"), None), AST.Enumerator(_id("B"), AST.IntLiteral(3))])},
          "tags": {"E": AST.EnumType(_id("E"), [AST.Enumerator(_id("A"), None), AST.Enumerator(_id("B"), AST.IntLiteral(3))])}}),
        ("int f(int a, ...) { return a; }",
         {"idents": {"f": AST.FunctionType(_bt("int"), [AST.Param(_id("a"), _bt("int"))], True)},
          "tags": {}}),
        ("typedef struct S { int x; } S; S *p;",
         {"idents": {"S": AST.StructType(_id("S"), [AST.Field(_id("x"), _bt("int"), None)]),
                     "p": AST.PointerType(AST.StructType(_id("S"), [AST.Field(_id("x"), _bt("int"), None)]))},
          "tags": {"S": AST.StructType(_id("S"), [AST.Field(_id("x"), _bt("int"), None)])}}),
        ("typedef int T; typedef T U; U x;",
         {"idents": {"T": _bt("int"), "U": _bt("int"), "x": _bt("int")}, "tags": {}}),
        ("typedef int (*FP)(int); FP f;",
         {"idents": {"FP": AST.PointerType(AST.FunctionType(_bt("int"), [AST.Param(None, _bt("int"))], False)),
                     "f": AST.PointerType(AST.FunctionType(_bt("int"), [AST.Param(None, _bt("int"))], False))},
          "tags": {}}),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            program = _resolve_program(source)
            for name, ctype in expected["idents"].items():
                assert _ident(program.scope, name).ctype == ctype
            for name, ctype in expected["tags"].items():
                assert _tag(program.scope, name).ctype == ctype


def test_param_scope_types(subtests: pytest.Subtests) -> None:
    cases = [
        ("int f(int a, int b) { return a + b; }",
         {"a": _bt("int"), "b": _bt("int")}),
        ("int f(int *p, const int *q) { return *p + *q; }",
         {"p": AST.PointerType(_bt("int")), "q": AST.PointerType(_bt("int"))}),
        ("int f(struct S { int x; } s) { return s.x; }",
         {"s": AST.StructType(_id("S"), [AST.Field(_id("x"), _bt("int"), None)])}),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            program = _resolve_program(source)
            item = program.items[0]
            assert isinstance(item, AST.FunctionDef)
            for name, ctype in expected.items():
                assert _ident(item.body.scope, name).ctype == ctype
