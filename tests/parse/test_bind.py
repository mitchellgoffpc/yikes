from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.bind import bind
from yikes.parse.parse import parse


def _bind_program(source: str) -> AST.Program:
    return bind(parse(source))

def _idents(scope: AST.Scope) -> dict[str, AST.SymbolKind]:
    return {name: symbol.kind for name, symbol in scope.idents.items()}

def _tags(scope: AST.Scope) -> dict[str, AST.SymbolKind]:
    return {name: symbol.kind for name, symbol in scope.tags.items()}


def test_global_bindings(subtests: pytest.Subtests) -> None:
    cases = [
        ("typedef int T; T x; int y;",
         {"idents": {"T": AST.SymbolKind.TYPEDEF, "x": AST.SymbolKind.VAR, "y": AST.SymbolKind.VAR}, "tags": {}}),
        ("enum E { A, B = 2 }; enum E e;",
         {"idents": {"A": AST.SymbolKind.ENUM_CONST, "B": AST.SymbolKind.ENUM_CONST, "e": AST.SymbolKind.VAR},
          "tags": {"E": AST.SymbolKind.TAG}}),
        ("struct S { int x; }; struct S s;",
         {"idents": {"s": AST.SymbolKind.VAR}, "tags": {"S": AST.SymbolKind.TAG}}),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            program = _bind_program(source)
            assert _idents(program.scope) == expected["idents"]
            assert _tags(program.scope) == expected["tags"]


def test_function_and_block_scopes(subtests: pytest.Subtests) -> None:
    cases = [
        ("int f(int a, int b) { int c; { int d; } }",
         {"body": {"a": AST.SymbolKind.VAR, "b": AST.SymbolKind.VAR, "c": AST.SymbolKind.VAR}, "inner": {"d": AST.SymbolKind.VAR}}),
        ("int f() { for (int i = 0; i < 3; i++) { int j; } }",
         {"body": {}, "for": {"i": AST.SymbolKind.VAR}, "inner": {"j": AST.SymbolKind.VAR}}),
        ("int f() { label: goto label; }",
         {"labels": {"label": AST.SymbolKind.LABEL}}),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            program = _bind_program(source)
            item = program.items[0]
            assert isinstance(item, AST.FunctionDef)

            if "labels" in expected:
                assert {name: symbol.kind for name, symbol in item.scope.labels.items()} == expected["labels"]
                continue

            assert _idents(item.body.scope) == expected["body"]
            if "for" in expected:
                for_stmt = item.body.items[0]
                assert isinstance(for_stmt, AST.For)
                assert _idents(for_stmt.scope) == expected["for"]
                body = for_stmt.body
                assert isinstance(body, AST.Block)
                assert _idents(body.scope) == expected["inner"]
            else:
                inner = item.body.items[1]
                assert isinstance(inner, AST.Block)
                assert _idents(inner.scope) == expected["inner"]
