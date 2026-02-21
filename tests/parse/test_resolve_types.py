from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.bind import bind
from yikes.parse.parse import parse
from yikes.parse.resolve_types import resolve_types


def _resolve_program(source: str) -> AST.Program:
    program = bind(parse(source))
    return resolve_types(program)


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
         {"idents": {"T": AST.BuiltinType("int"), "x": AST.BuiltinType("int")}, "tags": {}}),
        ("struct S { int x; }; struct S s;",
         {"idents": {"s": AST.StructType("S", [AST.Field("x", AST.BuiltinType("int"), None)])},
          "tags": {"S": AST.StructType("S", [AST.Field("x", AST.BuiltinType("int"), None)])}}),
        ("union U { int x; char y; }; union U u;",
         {"idents": {"u": AST.UnionType("U", [AST.Field("x", AST.BuiltinType("int"), None), AST.Field("y", AST.BuiltinType("char"), None)])},
          "tags": {"U": AST.UnionType("U", [AST.Field("x", AST.BuiltinType("int"), None), AST.Field("y", AST.BuiltinType("char"), None)])}}),
        ("enum E { A, B = 3 }; enum E e;",
         {"idents": {"e": AST.EnumType("E", [AST.Enumerator("A", None), AST.Enumerator("B", AST.IntLiteral(3))])},
          "tags": {"E": AST.EnumType("E", [AST.Enumerator("A", None), AST.Enumerator("B", AST.IntLiteral(3))])}}),
        ("int f(int a, ...) { return a; }",
         {"idents": {"f": AST.FunctionType(AST.BuiltinType("int"), [AST.Param("a", AST.BuiltinType("int"))], True)},
          "tags": {}}),
        ("typedef struct S { int x; } S; S *p;",
         {"idents": {"S": AST.StructType("S", [AST.Field("x", AST.BuiltinType("int"), None)]),
                     "p": AST.PointerType(AST.StructType("S", [AST.Field("x", AST.BuiltinType("int"), None)]))},
          "tags": {"S": AST.StructType("S", [AST.Field("x", AST.BuiltinType("int"), None)])}}),
        ("typedef int T; typedef T U; U x;",
         {"idents": {"T": AST.BuiltinType("int"), "U": AST.BuiltinType("int"), "x": AST.BuiltinType("int")}, "tags": {}}),
        ("typedef int (*FP)(int); FP f;",
         {"idents": {"FP": AST.PointerType(AST.FunctionType(AST.BuiltinType("int"), [AST.Param("", AST.BuiltinType("int"))], False)),
                     "f": AST.PointerType(AST.FunctionType(AST.BuiltinType("int"), [AST.Param("", AST.BuiltinType("int"))], False))},
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
         {"a": AST.BuiltinType("int"), "b": AST.BuiltinType("int")}),
        ("int f(int *p, const int *q) { return *p + *q; }",
         {"p": AST.PointerType(AST.BuiltinType("int")), "q": AST.PointerType(AST.BuiltinType("int"))}),
        ("int f(struct S { int x; } s) { return s.x; }",
         {"s": AST.StructType("S", [AST.Field("x", AST.BuiltinType("int"), None)])}),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            program = _resolve_program(source)
            item = program.items[0]
            assert isinstance(item, AST.FunctionDef)
            for name, ctype in expected.items():
                assert _ident(item.body.scope, name).ctype == ctype
