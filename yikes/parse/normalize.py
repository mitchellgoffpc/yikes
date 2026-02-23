from __future__ import annotations

from typing import cast, get_args

from yikes.parse import ast as AST  # noqa: N812

_CTYPE_CLASSES = cast(tuple[type, ...], get_args(AST.CType))


def normalize(program: AST.Program) -> AST.Program:
    items: list[AST.ExternalDecl] = []
    for item in program.items:
        items.extend(_normalize_external_decl(item))
    return AST.Program(items, scope=AST.Scope())

def _normalize_external_decl(node: AST.ExternalDecl) -> list[AST.ExternalDecl]:
    match node:
        case AST.FunctionDef():
            return [AST.FunctionDef(node.name, node.specs, node.params, node.return_type, node.variadic, _normalize_block(node.body), scope=AST.Scope())]
        case AST.VarDecl():
            return [AST.VarDecl(node.name, node.ctype, _normalize_initializer(node.init) if node.init else None)]
        case AST.TypeDef():
            return [node]
        case AST.StructDef():
            return [AST.StructDef(node.name, node.specs, _normalize_fields(node.fields))]
        case AST.UnionDef():
            return [AST.UnionDef(node.name, node.specs, _normalize_fields(node.fields))]
        case AST.EnumDef():
            return [AST.EnumDef(node.name, node.specs, [_normalize_enumerator(value) for value in node.values])]
        case _:
            raise TypeError(f"Unknown external decl: {type(node).__name__}")

def _normalize_stmt(node: AST.Stmt) -> AST.Stmt:
    match node:
        case AST.Block():
            return _normalize_block(node)
        case AST.VarDecl():
            return AST.VarDecl(node.name, node.ctype, _normalize_initializer(node.init) if node.init else None)
        case AST.TypeDef():
            return node
        case AST.StructDef():
            return AST.StructDef(node.name, node.specs, _normalize_fields(node.fields))
        case AST.UnionDef():
            return AST.UnionDef(node.name, node.specs, _normalize_fields(node.fields))
        case AST.EnumDef():
            return AST.EnumDef(node.name, node.specs, [_normalize_enumerator(value) for value in node.values])
        case AST.ExprStmt():
            return AST.ExprStmt(_normalize_expr(node.expr) if node.expr else None)
        case AST.Return():
            return AST.Return(_normalize_expr(node.value) if node.value else None)
        case AST.If():
            then = _ensure_block(_normalize_stmt(node.then))
            otherwise = _ensure_block(_normalize_stmt(node.otherwise)) if node.otherwise else None
            return AST.If(_normalize_expr(node.cond), then, otherwise)
        case AST.While():
            return AST.While(_normalize_expr(node.cond), _ensure_block(_normalize_stmt(node.body)))
        case AST.Break() | AST.Continue():
            return node
        case AST.Switch():
            return AST.Switch(_normalize_expr(node.expr), _normalize_block(node.body))
        case AST.Case():
            return AST.Case(_normalize_expr(node.value), _normalize_block(node.body))
        case AST.Default():
            return AST.Default(_normalize_block(node.body))
        case AST.Label():
            return AST.Label(node.name, _normalize_stmt(node.stmt))
        case AST.Goto():
            return node
        case _:
            raise TypeError(f"Unknown stmt: {type(node).__name__}")

def _normalize_stmt_items(node: AST.Stmt) -> list[AST.Stmt]:
    match node:
        case _:
            return [_normalize_stmt(node)]

def _normalize_expr(node: AST.Expr) -> AST.Expr:
    match node:
        case AST.Assign():
            return AST.Assign(_normalize_expr(node.target), _normalize_expr(node.value))
        case AST.Binary():
            return AST.Binary(node.op, _normalize_expr(node.left), _normalize_expr(node.right))
        case AST.Unary():
            return AST.Unary(node.op, _normalize_expr(node.value))
        case AST.IncDec():
            return AST.IncDec(node.op, _normalize_expr(node.value), node.is_postfix)
        case AST.Call():
            return AST.Call(_normalize_expr(node.func), [_normalize_expr(arg) for arg in node.args])
        case AST.Member():
            return AST.Member(_normalize_expr(node.value), node.name, node.through_pointer)
        case AST.ArraySubscript():
            return AST.Unary("*", AST.Binary("+", _normalize_expr(node.value), _normalize_expr(node.index)))
        case AST.Conditional():
            return AST.Conditional(_normalize_expr(node.cond), _normalize_expr(node.then), _normalize_expr(node.otherwise))
        case AST.Cast():
            return AST.Cast(node.target_type, _normalize_expr(node.value))
        case AST.Sizeof(value=value) if isinstance(value, _CTYPE_CLASSES):
            return node
        case AST.Sizeof():
            return AST.Sizeof(_normalize_expr(cast(AST.Expr, node.value)))
        case AST.CompoundLiteral():
            return AST.CompoundLiteral(node.ctype, _normalize_initializer(node.value))
        case AST.IntLiteral() | AST.BoolLiteral() | AST.FloatLiteral() | AST.CharLiteral() | AST.StringLiteral() | AST.Identifier():
            return node
        case _:
            raise TypeError(f"Unknown expr: {type(node).__name__}")

def _normalize_block(block: AST.Block) -> AST.Block:
    items: list[AST.Stmt] = []
    for item in block.items:
        items.extend(_normalize_stmt_items(item))
    return AST.Block(items, scope=AST.Scope())

def _normalize_fields(fields: list[AST.Field] | None) -> list[AST.Field] | None:
    if fields is None:
        return None
    return [AST.Field(field.name, field.ctype, _normalize_expr(field.bit_width) if field.bit_width else None) for field in fields]

def _normalize_enumerator(value: AST.Enumerator) -> AST.Enumerator:
    return AST.Enumerator(value.name, _normalize_expr(value.value) if value.value else None)

def _normalize_initializer(node: AST.Initializer) -> AST.Initializer:
    match node:
        case AST.InitList():
            return AST.InitList([_normalize_initializer_item(item) for item in node.items])
        case AST.CompoundLiteral():
            return AST.CompoundLiteral(node.ctype, _normalize_initializer(node.value))
        case _:
            return _normalize_expr(node)

def _normalize_initializer_item(item: AST.InitializerItem) -> AST.InitializerItem:
    return AST.InitializerItem([_normalize_designator(desig) for desig in item.designators], _normalize_initializer(item.value))

def _normalize_designator(desig: AST.Designator) -> AST.Designator:
    return AST.Designator(desig.field, _normalize_expr(desig.index) if desig.index else None)

def _ensure_block(stmt: AST.Stmt) -> AST.Block:
    if isinstance(stmt, AST.Block):
        return stmt
    return AST.Block([stmt], scope=AST.Scope())
