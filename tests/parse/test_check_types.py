from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.bind import bind
from yikes.parse.check_types import check_types
from yikes.parse.parse import parse
from yikes.parse.resolve_types import resolve_types


def _type_program(source: str) -> AST.Program:
    return check_types(resolve_types(bind(parse(source))))


def _bt(name: str) -> AST.BuiltinType:
    return AST.BuiltinType([AST.TypeKeyword(name)])


def _type_key(ctype: AST.CType) -> tuple:
    match ctype:
        case AST.BuiltinType(keywords=keywords):
            return ("builtin", tuple(sorted(kw.name for kw in keywords)))
        case AST.PointerType(base=base):
            return ("ptr", _type_key(base))
        case AST.ArrayType(base=base, size=size):
            size_val = size.value if isinstance(size, AST.IntLiteral) else None
            return ("array", _type_key(base), size_val)
        case AST.FunctionType(return_type=return_type, params=params, variadic=variadic):
            return ("func", _type_key(return_type), tuple(_type_key(p.ctype) for p in params), variadic)
        case AST.StructType(name=name):
            return ("struct", name.name if name else None)
        case AST.UnionType(name=name):
            return ("union", name.name if name else None)
        case AST.EnumType(name=name):
            return ("enum", name.name if name else None)
        case AST.NamedType(name=name):
            return ("named", name.name)
    return ("unknown", id(ctype))


def test_expression_types(subtests: pytest.Subtests) -> None:
    cases = [
        ("1;", _bt("int")),
        ("1.0;", _bt("float")),
        ("'a';", _bt("char")),
        ('"hi";', AST.ArrayType(_bt("char"), None)),
        ("1 && 2;", _bt("bool")),
        ("1 ? 2 : 3.0;", _bt("float")),
        ("int *p; p + 1;", AST.PointerType(_bt("int"))),
        ("int *p; int *q; p - q;", _bt("int")),
        ("struct A { int x; }; struct A a; a.x;", _bt("int")),
    ]

    for body, expected in cases:
        with subtests.test(body=body):
            program = _type_program(f"int f() {{ {body} }}")
            item = program.items[0]
            assert isinstance(item, AST.FunctionDef)
            stmt = item.body.items[-1]
            assert isinstance(stmt, AST.ExprStmt)
            assert stmt.expr is not None
            assert stmt.expr.expr_type is not None
            assert _type_key(stmt.expr.expr_type) == _type_key(expected)


def test_external_decl_errors(subtests: pytest.Subtests) -> None:
    cases = [
        ("void x;", r"Object type required at \d+:\d+"),
        ("struct S s;", r"Incomplete object type at \d+:\d+"),
    ]

    for source, error_match in cases:
        with subtests.test(source=source), pytest.raises(ValueError, match=error_match):
            _type_program(source)


def test_statement_type_errors(subtests: pytest.Subtests) -> None:
    cases = [
        ("int f() { return; }", r"Expected void return at \d+:\d+"),
        ("void f() { return 1; }", r"Incompatible types in assignment at \d+:\d+"),
        ("typedef struct S { int x; } S; int f() { S s; if (s) return 1; return 0; }", r"Expected scalar type at \d+:\d+"),
        ("typedef struct S { int x; } S; int f() { S s; while (s) return 1; return 0; }", r"Expected scalar type at \d+:\d+"),
        ("int f() { switch (1.0) { default: break; } }", r"Expected integer type at \d+:\d+"),
    ]

    for source, error_match in cases:
        with subtests.test(source=source), pytest.raises(ValueError, match=error_match):
            _type_program(source)


def test_expression_errors(subtests: pytest.Subtests) -> None:
    cases = [
        ("int f() { return x; }", r"Unknown identifier 'x' at \d+:\d+"),
        ("typedef int T; int f() { return T; }", r"'T' is a typedef at \d+:\d+"),
        ("int f() { 1 = 2; }", r"Expected lvalue at \d+:\d+"),
        ("int f() { int a[2]; a = 1; }", r"Expected modifiable lvalue at \d+:\d+"),
        ("int f() { int *p; int x; p = x; }", r"Incompatible types in assignment at \d+:\d+"),
        ("int f() { return &1; }", r"Expected lvalue at \d+:\d+"),
        ("int f() { return *1; }", r"Cannot dereference non-pointer at \d+:\d+"),
        ("int f() { int *p; return -p; }", r"Expected arithmetic type at \d+:\d+"),
        ("int f() { float x; return ~x; }", r"Expected integer type at \d+:\d+"),
        ("typedef struct S { int x; } S; int f() { S s; s++; return 0; }", r"Expected scalar type at \d+:\d+"),
        ("typedef struct S { int x; } S; int f() { S s; return s && 1; }", r"Expected scalar type at \d+:\d+"),
        ("int f() { float x; return x & 1; }", r"Expected integer type at \d+:\d+"),
        ("int f() { float x; return x << 1; }", r"Expected integer type at \d+:\d+"),
        ("int f() { return 5.0 % 2; }", r"Expected integer type at \d+:\d+"),
        ("int f() { int *p; int *q; return p + q; }", r"Expected arithmetic type at \d+:\d+"),
        ("int f() { int *p; char *q; return p - q; }", r"Pointer subtraction with incompatible types at \d+:\d+"),
        ("int f() { int *p; int x; return p == x; }", r"Incompatible types for comparison at \d+:\d+"),
        ("int f() { int *p; int x; return 1 ? p : x; }", r"Incompatible types in conditional expression at \d+:\d+"),
        ("int f() { struct S *p; return p->x; }", r"Member access on incomplete type at \d+:\d+"),
        ("typedef struct S { int x; } S; int f() { S s; return s->x; }", r"Member access through non-pointer at \d+:\d+"),
        ("int f() { int x; return x.y; }", r"Member access on non-struct/union at \d+:\d+"),
        ("typedef struct S { int x; } S; int f() { S s; return s.y; }", r"Unknown field 'y' at \d+:\d+"),
        ("int f() { int x; x(1); }", r"Called object is not a function at \d+:\d+"),
        ("int g(int a, int b) { return a + b; } int f() { g(1); return 0; }", r"Incorrect argument count at \d+:\d+"),
        ("int g(int a, ...) { return a; } int f() { g(); return 0; }", r"Not enough arguments for variadic function at \d+:\d+"),
        ("int g(int *p) { return 0; } int f() { int x; g(x); return 0; }", r"Incompatible types in assignment at \d+:\d+"),
        ("int f() { int x = {1}; return x; }", r"Initializer list used for non-aggregate type at \d+:\d+"),
        ("typedef struct S { int a; } S; int f() { S s = {1, 2}; return 0; }", r"Too many initializers at \d+:\d+"),
        ("typedef struct S { int a; } S; int f() { S s = { .b = 1 }; return 0; }", r"Unknown field 'b' at \d+:\d+"),
        ("int f() { int x = 1; int a[3] = { [x] = 1 }; return 0; }", r"Array designator is not a constant expression at \d+:\d+"),
        ("int f() { return (struct S)0; }", r"Cannot cast to incomplete type at \d+:\d+"),
        ("int f() { return sizeof f; }", r"Invalid sizeof operand at \d+:\d+"),
        ("int f() { return sizeof(struct S); }", r"Invalid sizeof operand at \d+:\d+"),
        ("int f() { (void){1}; return 0; }", r"Object type required at \d+:\d+"),
    ]

    for source, error_match in cases:
        with subtests.test(source=source), pytest.raises(ValueError, match=error_match):
            _type_program(source)
