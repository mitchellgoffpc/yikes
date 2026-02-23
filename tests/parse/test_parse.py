from __future__ import annotations

import pytest

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.parse import parse


def _bt(name: str) -> AST.BuiltinType:
    return AST.BuiltinType([AST.TypeKeyword(name)])

def _id(name: str) -> AST.Identifier:
    return AST.Identifier(name)

def _specs(ctype: AST.CType, *specs: AST.DeclSpec) -> AST.DeclSpecs:
    return AST.DeclSpecs(list(specs), ctype)

def _span(start_line: int, start_col: int, end_line: int, end_col: int) -> AST.Span:
    return AST.Span(AST.Position(start_line, start_col), AST.Position(end_line, end_col))

def _program(items: list[AST.ExternalDecl]) -> AST.Program:
    return AST.Program(items, AST.Scope())

def _block(items: list[AST.Stmt]) -> AST.Block:
    return AST.Block(items, scope=AST.Scope())

def _for(init: AST.Stmt | None, cond: AST.Expr | None, step: AST.Expr | None, body: AST.Stmt) -> AST.For:
    return AST.For(init, cond, step, body, scope=AST.Scope())

def _ptr(qualifiers: list[AST.TypeQualifier] | None = None, to: AST.Pointer | None = None) -> AST.Pointer:
    return AST.Pointer(qualifiers or [], to)

def _decl(name: str | None, *, pointer: AST.Pointer | None = None, nested: AST.Declarator | None = None,
          suffixes: list[AST.DirectSuffix] | None = None) -> AST.Declarator:
    ident = _id(name) if name is not None else None
    return AST.Declarator(pointer, AST.DirectDeclarator(ident, nested, suffixes or []))

def _init(name: str | None, init: AST.Initializer | None = None, *, pointer: AST.Pointer | None = None,
          nested: AST.Declarator | None = None, suffixes: list[AST.DirectSuffix] | None = None) -> AST.InitDeclarator:
    return AST.InitDeclarator(_decl(name, pointer=pointer, nested=nested, suffixes=suffixes), init)

def _param(specs: AST.DeclSpecs, declarator: AST.Declarator | AST.AbstractDeclarator | None = None) -> AST.ParamDecl:
    return AST.ParamDecl(specs, declarator)

def _func_suffix(params: list[AST.ParamDecl] | None, variadic: bool = False) -> AST.DirectSuffix:
    return AST.DirectSuffix(params or [], None, False, variadic)

def _array_suffix(size: AST.Expr | None) -> AST.DirectSuffix:
    return AST.DirectSuffix(None, size, False, False)

def _init_item(value: AST.Initializer, designators: list[AST.Designator] | None = None) -> AST.InitializerItem:
    return AST.InitializerItem(designators or [], value)

def _stmt(source: str) -> AST.Stmt:
    program = parse(f"int main() {{ {source} }}", with_spans=False)
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
         _program([
             AST.StructDef(_id("S"), [], [
                AST.Field(None, _bt("int"), AST.IntLiteral(1)),
                AST.Field(_id("a"), _bt("int"), AST.IntLiteral(2)),
                AST.Field(_id("b"), _bt("int"), None),
            ]),
        ])),
        ("union U { int x; char y; };",
         _program([
             AST.UnionDef(_id("U"), [], [AST.Field(_id("x"), _bt("int"), None), AST.Field(_id("y"), _bt("char"), None)]),
         ])),
        ("enum E { A, B = 3 };",
         _program([
             AST.EnumDef(_id("E"), [], [AST.Enumerator(_id("A"), None), AST.Enumerator(_id("B"), AST.IntLiteral(3))]),
         ])),
        ("typedef int T; T x;",
         _program([
             AST.TypeDef(_id("T"), _bt("int")),
             AST.VarDecl(_id("x"), AST.NamedType(_id("T")), None),
         ])),
        ("typedef int T; T (*p)[3];",
         _program([
             AST.TypeDef(_id("T"), _bt("int")),
             AST.VarDecl(_id("p"), AST.PointerType(AST.ArrayType(AST.NamedType(_id("T")), AST.IntLiteral(3))), None),
         ])),
        ("typedef int T; T *x;",
         _program([
             AST.TypeDef(_id("T"), _bt("int")),
             AST.VarDecl(_id("x"), AST.PointerType(AST.NamedType(_id("T"))), None),
         ])),
        ("_Bool b;", _program([AST.VarDecl(_id("b"), _bt("_Bool"), None)])),
        ("struct S s; union U u; enum E e;",
         _program([
             AST.VarDecl(_id("s"), AST.StructType(_id("S"), None), None),
             AST.VarDecl(_id("u"), AST.UnionType(_id("U"), None), None),
             AST.VarDecl(_id("e"), AST.EnumType(_id("E"), None), None),
         ])),
        ("int *p; int f(int);",
         _program([
             AST.VarDecl(_id("p"), AST.PointerType(_bt("int")), None),
             AST.VarDecl(_id("f"), AST.FunctionType(_bt("int"), [AST.Param(None, _bt("int"))], False), None),
         ])),
        ("int add(int x, int y) { return x + y; }",
         _program([
             AST.FunctionDef(
                 _id("add"),
                 _specs(_bt("int")),
                 [AST.Param(_id("x"), _bt("int")), AST.Param(_id("y"), _bt("int"))],
                 _bt("int"),
                 False,
                 _block([AST.Return(AST.Binary("+", AST.Identifier("x"), AST.Identifier("y")))]),
                 scope=AST.Scope(),
             ),
         ])),
        ("int logf(int level, ...) { return level; }",
         _program([
             AST.FunctionDef(
                 _id("logf"),
                 _specs(_bt("int")),
                 [AST.Param(_id("level"), _bt("int"))],
                 _bt("int"),
                 True,
                 _block([AST.Return(AST.Identifier("level"))]),
                 scope=AST.Scope(),
             ),
         ])),
        ("int (*f(void))(int) { return 0; }",
         _program([
             AST.FunctionDef(
                 _id("f"),
                 _specs(_bt("int")),
                 [],
                 AST.PointerType(AST.FunctionType(_bt("int"), [AST.Param(None, _bt("int"))], False)),
                 False,
                 _block([AST.Return(AST.IntLiteral(0))]),
                 scope=AST.Scope(),
             ),
         ])),
        ("static inline int *ptr(void) { return 0; }",
         _program([
             AST.FunctionDef(
                 _id("ptr"),
                 _specs(_bt("int"), AST.StorageClassSpec("static"), AST.FunctionSpec("inline")),
                 [],
                 AST.PointerType(_bt("int")),
                 False,
                 _block([AST.Return(AST.IntLiteral(0))]),
                 scope=AST.Scope(),
             ),
         ])),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert parse(source, with_spans=False) == expected


def test_declarators_and_specs(subtests: pytest.Subtests) -> None:
    cases = [
        ("static const int (*fp), a[3], f(int [3], int *), g(int, ...);",
         _program([
             AST.VarDecl(_id("fp"), AST.PointerType(_bt("int")), None),
             AST.VarDecl(_id("a"), AST.ArrayType(_bt("int"), AST.IntLiteral(3)), None),
             AST.VarDecl(
                 _id("f"),
                 AST.FunctionType(
                     _bt("int"),
                     [
                         AST.Param(None, AST.ArrayType(_bt("int"), AST.IntLiteral(3))),
                         AST.Param(None, AST.PointerType(_bt("int"))),
                     ],
                     False,
                 ),
                 None,
             ),
             AST.VarDecl(
                 _id("g"),
                 AST.FunctionType(_bt("int"), [AST.Param(None, _bt("int"))], True),
                 None,
             ),
         ])),
        ("inline int f(void), g(int y);",
         _program([
             AST.VarDecl(_id("f"), AST.FunctionType(_bt("int"), [], False), None),
             AST.VarDecl(_id("g"), AST.FunctionType(_bt("int"), [AST.Param(_id("y"), _bt("int"))], False), None),
         ])),
        ("int f(int a[static 3]), g;",
         _program([
             AST.VarDecl(
                 _id("f"),
                 AST.FunctionType(
                     _bt("int"),
                     [AST.Param(_id("a"), AST.ArrayType(_bt("int"), AST.IntLiteral(3)))],
                     False,
                 ),
                 None,
             ),
             AST.VarDecl(_id("g"), _bt("int"), None),
         ])),
        ("const int *const p, *q;",
         _program([
             AST.VarDecl(_id("p"), AST.PointerType(_bt("int")), None),
             AST.VarDecl(_id("q"), AST.PointerType(_bt("int")), None),
         ])),
    ]

    for source, expected in cases:
        with subtests.test(source=source):
            assert parse(source, with_spans=False) == expected


def test_statements(subtests: pytest.Subtests) -> None:
    cases = [
        ("return;", AST.Return(None)),
        ("return 1;", AST.Return(AST.IntLiteral(1))),
        ("if (x) y; else z;",
         AST.If(AST.Identifier("x"), AST.ExprStmt(AST.Identifier("y")), AST.ExprStmt(AST.Identifier("z")))),
        ("while (x) y;", AST.While(AST.Identifier("x"), AST.ExprStmt(AST.Identifier("y")))),
        ("do x; while (y);", AST.DoWhile(AST.ExprStmt(AST.Identifier("x")), AST.Identifier("y"))),
        ("for (;;) x;", _for(None, None, None, AST.ExprStmt(AST.Identifier("x")))),
        ("for (i = 0; i < 3; i++) x;",
         _for(
             AST.ExprStmt(AST.Assign(AST.Identifier("i"), AST.IntLiteral(0))),
             AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
             AST.IncDec("++", AST.Identifier("i"), True),
             AST.ExprStmt(AST.Identifier("x")),
         )),
        ("for (int i = 0; i < 3; i = i + 1) x;",
         _for(
             AST.VarDecl(_id("i"), _bt("int"), AST.IntLiteral(0)),
             AST.Binary("<", AST.Identifier("i"), AST.IntLiteral(3)),
             AST.Assign(AST.Identifier("i"), AST.Binary("+", AST.Identifier("i"), AST.IntLiteral(1))),
             AST.ExprStmt(AST.Identifier("x")),
         )),
        ("break;", AST.Break()),
        ("continue;", AST.Continue()),
        ("switch (x) { case 1: y; default: z; }",
         AST.Switch(
             AST.Identifier("x"),
             _block([
                 AST.Case(AST.IntLiteral(1), _block([AST.ExprStmt(AST.Identifier("y"))])),
                 AST.Default(_block([AST.ExprStmt(AST.Identifier("z"))])),
             ]),
         )),
        ("label: goto label;", AST.Label(_id("label"), AST.Goto(_id("label")))),
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
        ("obj.field", AST.Member(AST.Identifier("obj"), _id("field"), False)),
        ("ptr->field", AST.Member(AST.Identifier("ptr"), _id("field"), True)),
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
         _program([
             AST.VarDecl(
                 _id("a"),
                 AST.ArrayType(_bt("int"), AST.IntLiteral(3)),
                 AST.InitList([
                     _init_item(AST.IntLiteral(1)),
                     _init_item(AST.IntLiteral(2)),
                     _init_item(AST.IntLiteral(3)),
                 ]),
             ),
         ])),
        ("int a[3] = { [1] = 2, [2] = 3 };",
         _program([
             AST.VarDecl(
                 _id("a"),
                 AST.ArrayType(_bt("int"), AST.IntLiteral(3)),
                 AST.InitList([
                     _init_item(AST.IntLiteral(2), [AST.Designator(None, AST.IntLiteral(1))]),
                     _init_item(AST.IntLiteral(3), [AST.Designator(None, AST.IntLiteral(2))]),
                 ]),
             ),
         ])),
        ("int x = { .a = 1, .b = 2 };",
         _program([
             AST.VarDecl(
                 _id("x"),
                 _bt("int"),
                 AST.InitList([
                     _init_item(AST.IntLiteral(1), [AST.Designator(_id("a"), None)]),
                     _init_item(AST.IntLiteral(2), [AST.Designator(_id("b"), None)]),
                 ]),
             ),
         ])),
        ("int a[2][2] = { {1, 2}, {3, 4} };",
         _program([
             AST.VarDecl(
                 _id("a"),
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
            assert parse(source, with_spans=False) == expected


def test_spans(subtests: pytest.Subtests) -> None:
    source = "int main() {\n  return 42;\n}\n"
    expected = AST.Program([
        AST.FunctionDef(
            AST.Identifier("main", _span(1, 5, 1, 9)),
            AST.DeclSpecs([], AST.BuiltinType([AST.TypeKeyword("int", _span(1, 1, 1, 4))], _span(1, 1, 1, 4)), _span(1, 1, 1, 4)),
            [],
            AST.BuiltinType([AST.TypeKeyword("int", _span(1, 1, 1, 4))], _span(1, 1, 1, 4)),
            False,
            AST.Block([AST.Return(AST.IntLiteral(42, _span(2, 10, 2, 12)), _span(2, 3, 2, 13))], scope=AST.Scope(), span=_span(1, 12, 3, 2)),
            scope=AST.Scope(),
            span=_span(1, 1, 3, 2),
        ),
    ], AST.Scope(), span=_span(1, 1, 3, 2))
    with subtests.test(source=source):
        assert parse(source) == expected

    source = "int x = { [1] = 2, .a = 3 };"
    expected = AST.Program([
        AST.VarDecl(
            AST.Identifier("x", _span(1, 5, 1, 6)),
            AST.BuiltinType([AST.TypeKeyword("int", _span(1, 1, 1, 4))], _span(1, 1, 1, 4)),
            AST.InitList([
                AST.InitializerItem(
                    [AST.Designator(None, AST.IntLiteral(1, _span(1, 12, 1, 13)), _span(1, 11, 1, 14))],
                    AST.IntLiteral(2, _span(1, 17, 1, 18)),
                    _span(1, 11, 1, 18),
                ),
                AST.InitializerItem(
                    [AST.Designator(AST.Identifier("a", _span(1, 21, 1, 22)), None, _span(1, 20, 1, 22))],
                    AST.IntLiteral(3, _span(1, 25, 1, 26)),
                    _span(1, 20, 1, 26),
                ),
            ], _span(1, 9, 1, 28)),
            _span(1, 1, 1, 29),
        ),
    ], AST.Scope(), span=_span(1, 1, 1, 29))
    with subtests.test(source=source):
        assert parse(source) == expected
