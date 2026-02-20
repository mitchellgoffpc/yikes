from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.parse import parse


def _bt(name: str) -> AST.BuiltinType:
    return AST.BuiltinType(name)

def _ts(name: str) -> AST.TypeSpec:
    return AST.TypeSpec(_bt(name))

def _ptr(qualifiers: list[AST.TypeQualifier] | None = None, to: AST.Pointer | None = None) -> AST.Pointer:
    return AST.Pointer(qualifiers or [], to)

def _decl(name: str | None, *, pointer: AST.Pointer | None = None, nested: AST.Declarator | None = None,
          suffixes: list[AST.DirectSuffix] | None = None) -> AST.Declarator:
    return AST.Declarator(pointer, AST.DirectDeclarator(name, nested, suffixes or []))

def _init(name: str | None, init: AST.Initializer | None = None, *, pointer: AST.Pointer | None = None,
          nested: AST.Declarator | None = None, suffixes: list[AST.DirectSuffix] | None = None) -> AST.InitDeclarator:
    return AST.InitDeclarator(_decl(name, pointer=pointer, nested=nested, suffixes=suffixes), init)

def _param(specs: list[AST.DeclSpec], declarator: AST.Declarator | AST.AbstractDeclarator | None = None) -> AST.ParamDecl:
    return AST.ParamDecl(specs, declarator)

def _func_suffix(params: list[AST.ParamDecl] | None, variadic: bool = False) -> AST.DirectSuffix:
    return AST.DirectSuffix(params or [], None, False, variadic)

def _array_suffix(size: AST.Expr | None) -> AST.DirectSuffix:
    return AST.DirectSuffix(None, size, False, False)

def _init_item(value: AST.Initializer, designators: list[AST.Designator] | None = None) -> AST.InitializerItem:
    return AST.InitializerItem(designators or [], value)

def _stmt(source: str) -> AST.Stmt:
    program = parse(f"int main() {{ {source} }}")
    item = program.items[0]
    assert isinstance(item, AST.FunctionDef)
    return item.body.items[0]

def _expr(source: str) -> AST.Expr:
    stmt = _stmt(f"{source};")
    assert isinstance(stmt, AST.ExprStmt)
    assert stmt.expr is not None
    return stmt.expr


def test_program_decls(subtests: pytest.Subtests) -> None:
    cases = [
        ("struct S { int :1; int a:2; int b; };",
         AST.Program([
             AST.StructDef("S", [
                 AST.Field(None, _bt("int"), AST.IntLiteral(1)),
                 AST.Field("a", _bt("int"), AST.IntLiteral(2)),
                 AST.Field("b", _bt("int"), None),
             ]),
         ])),
        ("union U { int x; char y; };",
         AST.Program([
             AST.UnionDef("U", [AST.Field("x", _bt("int"), None), AST.Field("y", _bt("char"), None)]),
         ])),
        ("enum E { A, B = 3 };",
         AST.Program([
             AST.EnumDef("E", [AST.Enumerator("A", None), AST.Enumerator("B", AST.IntLiteral(3))]),
         ])),
        ("typedef int T; T x;",
         AST.Program([
             AST.TypeDef("T", _bt("int")),
             AST.VarDecl("x", AST.NamedType("T"), None),
         ])),
        ("typedef int T; T (*p)[3];",
         AST.Program([
             AST.TypeDef("T", _bt("int")),
             AST.VarDecl("p", AST.PointerType(AST.ArrayType(AST.NamedType("T"), AST.IntLiteral(3))), None),
         ])),
        ("typedef int T; T *x;",
         AST.Program([
             AST.TypeDef("T", _bt("int")),
             AST.VarDecl("x", AST.PointerType(AST.NamedType("T")), None),
         ])),
        ("_Bool b;", AST.Program([AST.VarDecl("b", _bt("_Bool"), None)])),
        ("struct S s; union U u; enum E e;",
         AST.Program([
             AST.VarDecl("s", AST.StructType("S", None), None),
             AST.VarDecl("u", AST.UnionType("U", None), None),
             AST.VarDecl("e", AST.EnumType("E", None), None),
         ])),
        ("int *p; int f(int);",
         AST.Program([
             AST.VarDecl("p", AST.PointerType(_bt("int")), None),
             AST.VarDecl("f", AST.FunctionType(_bt("int"), [AST.Param("", _bt("int"))], False), None),
         ])),
        ("int add(int x, int y) { return x + y; }",
         AST.Program([
             AST.FunctionDef(
                 "add",
                 [AST.Param("x", _bt("int")), AST.Param("y", _bt("int"))],
                 _bt("int"),
                 AST.Block([AST.Return(AST.Binary("+", AST.Identifier("x"), AST.Identifier("y")))]),
             ),
         ])),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert parse(source) == expected


def test_declarators_and_specs(subtests: pytest.Subtests) -> None:
    cases = [
        ("static const int (*fp), a[3], f(int [3], int *), g(int, ...);",
         AST.Program([
             AST.Declaration(
                 [AST.StorageClassSpec("static"), AST.TypeQualifier("const"), _ts("int")],
                 [_init(None, nested=_decl("fp", pointer=_ptr())),
                  _init("a", suffixes=[_array_suffix(AST.IntLiteral(3))]),
                  _init("f", suffixes=[_func_suffix([
                      _param([_ts("int")], AST.AbstractDeclarator(None, AST.DirectAbstractDeclarator(None, [_array_suffix(AST.IntLiteral(3))]))),
                      _param([_ts("int")], AST.AbstractDeclarator(_ptr(), None)),
                  ])]),
                  _init("g", suffixes=[_func_suffix([_param([_ts("int")])], variadic=True)])],
             ),
         ])),
        ("inline int f(void), g(int y);",
         AST.Program([
             AST.Declaration(
                 [AST.FunctionSpec("inline"), _ts("int")],
                 [_init("f", suffixes=[_func_suffix([])]),
                  _init("g", suffixes=[_func_suffix([_param([_ts("int")], _decl("y"))])])],
             ),
         ])),
        ("int f(int a[static 3]), g;",
         AST.Program([
             AST.Declaration(
                 [_ts("int")],
                 [_init("f", suffixes=[_func_suffix([_param([_ts("int")], _decl("a", suffixes=[AST.DirectSuffix(None, AST.IntLiteral(3), True, False)]))])]),
                  _init("g")],
             ),
         ])),
        ("const int *const p, *q;",
         AST.Program([
             AST.Declaration(
                 [AST.TypeQualifier("const"), _ts("int")],
                 [_init("p", pointer=_ptr([AST.TypeQualifier("const")])),
                  _init("q", pointer=_ptr())],
             ),
         ])),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert parse(source) == expected


def test_statements(subtests: pytest.Subtests) -> None:
    cases = [
        ("return;", AST.Return(None)),
        ("return 1;", AST.Return(AST.IntLiteral(1))),
        ("if (x) y; else z;",
         AST.If(AST.Identifier("x"), AST.ExprStmt(AST.Identifier("y")), AST.ExprStmt(AST.Identifier("z")))),
        ("while (x) y;", AST.While(AST.Identifier("x"), AST.ExprStmt(AST.Identifier("y")))),
        ("do x; while (y);", AST.DoWhile(AST.ExprStmt(AST.Identifier("x")), AST.Identifier("y"))),
        ("for (;;) x;", AST.For(None, None, None, AST.ExprStmt(AST.Identifier("x")))),
        ("for (i = 0; i < 3; i++) x;",
         AST.For(
             AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.IntLiteral(0))),
             AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
             AST.IncDec("++", AST.Identifier("i"), True),
             AST.ExprStmt(AST.Identifier("x")),
         )),
        ("for (int i = 0; i < 3; i = i + 1) x;",
         AST.For(
             AST.VarDecl("i", _bt("int"), AST.IntLiteral(0)),
             AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
             AST.Assign(AST.Identifier("i"), AST.Binary("+", AST.Identifier("i"), AST.IntLiteral(1))),
             AST.ExprStmt(AST.Identifier("x")),
         )),
        ("break;", AST.Break()),
        ("continue;", AST.Continue()),
        ("switch (x) { case 1: y; default: z; }",
         AST.Switch(
             AST.Identifier("x"),
             AST.Block([
                 AST.Case(AST.IntLiteral(1), AST.Block([AST.ExprStmt(AST.Identifier("y"))])),
                 AST.Default(AST.Block([AST.ExprStmt(AST.Identifier("z"))])),
             ]),
         )),
        ("label: goto label;", AST.Label("label", AST.Goto("label"))),
        (";", AST.ExprStmt(None)),
        ("x;", AST.ExprStmt(AST.Identifier("x"))),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _stmt(source) == expected


def test_expressions(subtests: pytest.Subtests) -> None:
    cases = [
        ("a, b, c", AST.Binary(",", AST.Binary(",", AST.Identifier("a"), AST.Identifier("b")), AST.Identifier("c"))),
        ("a = b", AST.Assign(AST.Identifier("a"), AST.Identifier("b"))),
        ("a += 1", AST.Assign(AST.Identifier("a"), AST.Binary("+", AST.Identifier("a"), AST.IntLiteral(1)))),
        ("a ? b : c", AST.Conditional(AST.Identifier("a"), AST.Identifier("b"), AST.Identifier("c"))),
        ("a || b && c", AST.Binary("||", AST.Identifier("a"), AST.Binary("&&", AST.Identifier("b"), AST.Identifier("c")))),
        ("a | b ^ c & d",
         AST.Binary(
             "|",
             AST.Identifier("a"),
             AST.Binary("^", AST.Identifier("b"), AST.Binary("&", AST.Identifier("c"), AST.Identifier("d"))),
         )),
        ("a == b", AST.Binary("==", AST.Identifier("a"), AST.Identifier("b"))),
        ("a < b", AST.Binary("<", AST.Identifier("a"), AST.Identifier("b"))),
        ("a << 2", AST.Binary("<<", AST.Identifier("a"), AST.IntLiteral(2))),
        ("a + b * c", AST.Binary("+", AST.Identifier("a"), AST.Binary("*", AST.Identifier("b"), AST.Identifier("c")))),
        ("++a", AST.IncDec("++", AST.Identifier("a"), False)),
        ("a--", AST.IncDec("--", AST.Identifier("a"), True)),
        ("!a", AST.Unary("!", AST.Identifier("a"))),
        ("~a", AST.Unary("~", AST.Identifier("a"))),
        ("-a", AST.Unary("-", AST.Identifier("a"))),
        ("*p", AST.Unary("*", AST.Identifier("p"))),
        ("&x", AST.Unary("&", AST.Identifier("x"))),
        ("f(1, 2)", AST.Call(AST.Identifier("f"), [AST.IntLiteral(1), AST.IntLiteral(2)])),
        ("arr[3]", AST.ArraySubscript(AST.Identifier("arr"), AST.IntLiteral(3))),
        ("obj.field", AST.Member(AST.Identifier("obj"), "field", False)),
        ("ptr->field", AST.Member(AST.Identifier("ptr"), "field", True)),
        ("(int) x", AST.Cast(_bt("int"), AST.Identifier("x"))),
        ("sizeof x", AST.Sizeof(AST.Identifier("x"))),
        ("sizeof(int)", AST.Sizeof(_bt("int"))),
        ("(int){1}", AST.CompoundLiteral(_bt("int"), AST.InitList([_init_item(AST.IntLiteral(1))]))),
        ("42", AST.IntLiteral(42)),
        ("3.5", AST.FloatLiteral(3.5)),
        ("'a'", AST.CharLiteral("a")),
        ("\"hi\"", AST.StringLiteral("hi")),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert _expr(source) == expected


def test_initializers(subtests: pytest.Subtests) -> None:
    cases = [
        ("int a[3] = {1, 2, 3};",
         AST.Program([
             AST.VarDecl(
                 "a",
                 AST.ArrayType(_bt("int"), AST.IntLiteral(3)),
                 AST.InitList([
                     _init_item(AST.IntLiteral(1)),
                     _init_item(AST.IntLiteral(2)),
                     _init_item(AST.IntLiteral(3)),
                 ]),
             ),
         ])),
        ("int a[3] = { [1] = 2, [2] = 3 };",
         AST.Program([
             AST.VarDecl(
                 "a",
                 AST.ArrayType(_bt("int"), AST.IntLiteral(3)),
                 AST.InitList([
                     _init_item(AST.IntLiteral(2), [AST.Designator(None, AST.IntLiteral(1))]),
                     _init_item(AST.IntLiteral(3), [AST.Designator(None, AST.IntLiteral(2))]),
                 ]),
             ),
         ])),
        ("int x = { .a = 1, .b = 2 };",
         AST.Program([
             AST.VarDecl(
                 "x",
                 _bt("int"),
                 AST.InitList([
                     _init_item(AST.IntLiteral(1), [AST.Designator("a", None)]),
                     _init_item(AST.IntLiteral(2), [AST.Designator("b", None)]),
                 ]),
             ),
         ])),
        ("int a[2][2] = { {1, 2}, {3, 4} };",
         AST.Program([
             AST.VarDecl(
                 "a",
                 AST.ArrayType(AST.ArrayType(_bt("int"), AST.IntLiteral(2)), AST.IntLiteral(2)),
                 AST.InitList([
                     _init_item(AST.InitList([
                         _init_item(AST.IntLiteral(1)),
                         _init_item(AST.IntLiteral(2)),
                     ])),
                     _init_item(AST.InitList([
                         _init_item(AST.IntLiteral(3)),
                         _init_item(AST.IntLiteral(4)),
                     ])),
                 ]),
             ),
         ])),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert parse(source) == expected
