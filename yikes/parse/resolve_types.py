from __future__ import annotations

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.helpers import const_eval, error, is_complete, lookup_ident


def resolve_types(program: AST.Program) -> AST.Program:
    scopes: list[AST.Scope] = [program.scope]
    items = [_resolve_external_decl(item, scopes) for item in program.items]
    return program._replace(items=items)


def _resolve_external_decl(node: AST.ExternalDecl, scopes: list[AST.Scope]) -> AST.ExternalDecl:
    match node:
        case AST.FunctionDef():
            return _resolve_function_def(node, scopes)
        case AST.VarDecl():
            return _resolve_var_decl(node, scopes)
        case AST.TypeDef():
            return _resolve_type_def(node, scopes)
        case AST.StructDef():
            return node._replace(ctype=_resolve_struct_def(node.ctype, scopes))
        case AST.UnionDef():
            return node._replace(ctype=_resolve_union_def(node.ctype, scopes))
        case AST.EnumDef():
            return node._replace(ctype=_resolve_enum_def(node.ctype, scopes))


def _resolve_stmt(node: AST.Stmt, scopes: list[AST.Scope]) -> AST.Stmt:
    match node:
        case AST.Block():
            return _resolve_block(node, scopes)
        case AST.VarDecl():
            return _resolve_var_decl(node, scopes)
        case AST.TypeDef():
            return _resolve_type_def(node, scopes)
        case AST.StructDef():
            return node._replace(ctype=_resolve_struct_def(node.ctype, scopes))
        case AST.UnionDef():
            return node._replace(ctype=_resolve_union_def(node.ctype, scopes))
        case AST.EnumDef():
            return node._replace(ctype=_resolve_enum_def(node.ctype, scopes))
        case AST.ExprStmt(expr=expr):
            expr = _resolve_expr(expr, scopes) if expr else None
            return node._replace(expr=expr)
        case AST.Return(value=value):
            value = _resolve_expr(value, scopes) if value else None
            return node._replace(value=value)
        case AST.Break() | AST.Continue() | AST.Goto():
            return node
        case AST.If(cond=cond, then=then, otherwise=otherwise):
            cond = _resolve_expr(cond, scopes)
            then = _resolve_block(then, scopes)
            otherwise = _resolve_block(otherwise, scopes) if otherwise else None
            return node._replace(cond=cond, then=then, otherwise=otherwise)
        case AST.While(cond=cond, body=body):
            cond = _resolve_expr(cond, scopes)
            body = _resolve_block(body, scopes)
            return node._replace(cond=cond, body=body)
        case AST.Switch(expr=expr, body=body):
            expr = _resolve_expr(expr, scopes)
            body = _resolve_block(body, scopes)
            return node._replace(expr=expr, body=body)
        case AST.Case(value=value, body=body):
            value = _resolve_expr(value, scopes)
            body = _resolve_block(body, scopes)
            return node._replace(value=value, body=body)
        case AST.Default(body=body):
            body = _resolve_block(body, scopes)
            return node._replace(body=body)
        case AST.Label(stmt=stmt):
            stmt = _resolve_stmt(stmt, scopes)
            return node._replace(stmt=stmt)


def _resolve_block(block: AST.Block, scopes: list[AST.Scope]) -> AST.Block:
    block_scopes = [*scopes, block.scope]
    items = [_resolve_stmt(item, block_scopes) for item in block.items]
    return block._replace(items=items)


def _resolve_var_decl(node: AST.VarDecl, scopes: list[AST.Scope]) -> AST.VarDecl:
    resolved = _resolve_ctype(node.ctype, scopes)
    init = _resolve_initializer(node.init, scopes) if node.init else None
    scopes[-1].idents[node.name.name].ctype = resolved
    return node._replace(ctype=resolved, init=init)


def _resolve_type_def(node: AST.TypeDef, scopes: list[AST.Scope]) -> AST.TypeDef:
    resolved = _resolve_ctype(node.ctype, scopes)
    scopes[-1].idents[node.name.name].ctype = resolved
    return node._replace(ctype=resolved)


def _resolve_function_def(node: AST.FunctionDef, scopes: list[AST.Scope]) -> AST.FunctionDef:
    resolved_ctype = _resolve_ctype(node.ctype, scopes)
    if not isinstance(resolved_ctype, AST.FunctionType):
        error(node.name.span, "Function type required")
    if isinstance(resolved_ctype.return_type, (AST.ArrayType, AST.FunctionType)):
        error(node.name.span, "Function cannot return array or function type")
    scopes[-1].idents[node.name.name].ctype = resolved_ctype
    function_scopes = [*scopes, node.body.scope]
    for param in resolved_ctype.params:
        if param.name:
            function_scopes[-1].idents[param.name.name].ctype = param.ctype
    body = _resolve_block(node.body, function_scopes)
    return node._replace(ctype=resolved_ctype, body=body)


def _resolve_struct_def(ctype: AST.StructType, scopes: list[AST.Scope]) -> AST.StructType:
    if ctype.fields is None:
        return ctype
    resolved_fields = [_resolve_field(field, scopes) for field in ctype.fields]
    resolved = AST.StructType(ctype.name, resolved_fields)
    if ctype.name:
        scopes[-1].tags[ctype.name.name].ctype = resolved
    return resolved


def _resolve_union_def(ctype: AST.UnionType, scopes: list[AST.Scope]) -> AST.UnionType:
    if ctype.fields is None:
        return ctype
    resolved_fields = [_resolve_field(field, scopes) for field in ctype.fields]
    resolved = AST.UnionType(ctype.name, resolved_fields)
    if ctype.name:
        scopes[-1].tags[ctype.name.name].ctype = resolved
    return resolved


def _resolve_enum_def(ctype: AST.EnumType, scopes: list[AST.Scope]) -> AST.EnumType:
    if ctype.values is None:
        return ctype
    resolved_values = [_resolve_enumerator(value, scopes) for value in ctype.values]
    resolved = AST.EnumType(ctype.name, resolved_values)
    if ctype.name:
        scopes[-1].tags[ctype.name.name].ctype = resolved
    return resolved


def _resolve_enumerator(enumerator: AST.Enumerator, scopes: list[AST.Scope]) -> AST.Enumerator:
    return enumerator._replace(value=_resolve_const_int(enumerator.value, scopes, "Enumerator value is not a constant expression"))


def _resolve_field(field: AST.Field, scopes: list[AST.Scope]) -> AST.Field:
    bit_width = _resolve_const_int(field.bit_width, scopes, "Bit-field width is not a constant expression")
    ctype = _resolve_ctype(field.ctype, scopes)
    if isinstance(ctype, (AST.FunctionType, AST.VoidType)) or not is_complete(ctype):
        error(field.span, "Invalid field type")
    return AST.Field(field.name, ctype, bit_width)


def _resolve_ctype(ctype: AST.CType, scopes: list[AST.Scope], seen: set[str] | None = None) -> AST.CType:
    match ctype:
        case AST.BuiltinType() | AST.VoidType():
            return ctype
        case AST.NamedType(name=name):
            return _resolve_named_type(name, scopes, seen)
        case AST.PointerType():
            return AST.PointerType(_resolve_ctype(ctype.base, scopes, seen))
        case AST.ArrayType():
            base = _resolve_ctype(ctype.base, scopes, seen)
            size = _resolve_const_int(ctype.size, scopes, "Array size is not a constant expression")
            return AST.ArrayType(base, size)
        case AST.FunctionType():
            resolved = AST.FunctionType(
                _resolve_ctype(ctype.return_type, scopes, seen),
                [AST.Param(param.name, _resolve_ctype(param.ctype, scopes)) for param in ctype.params],
                ctype.variadic,
            )
            if isinstance(resolved.return_type, (AST.ArrayType, AST.FunctionType)):
                error(ctype.span, "Function cannot return array or function type")
            return resolved
        case AST.StructType() | AST.UnionType() | AST.EnumType():
            return _resolve_tag_type(ctype, scopes)
        case _:
            raise TypeError(f"Unknown ctype: {type(ctype).__name__}")


def _resolve_named_type(name: AST.Identifier, scopes: list[AST.Scope], seen: set[str] | None) -> AST.CType:
    if seen is None:
        seen = set()
    if name.name in seen:
        error(name.span, f"Typedef cycle for '{name.name}'")
    seen.add(name.name)
    match lookup_ident(scopes, name.name):
        case AST.Symbol(kind=AST.SymbolKind.TYPEDEF, ctype=ctype) if ctype:
            return _resolve_ctype(ctype, scopes, seen)
    error(name.span, f"Unknown type name '{name.name}'")


def _resolve_tag_type(ctype: AST.StructType | AST.UnionType | AST.EnumType, scopes: list[AST.Scope]) -> AST.CType:
    if ctype.name and (symbol := _lookup_tag(scopes, ctype.name.name)) and symbol.ctype:
        match ctype:
            case AST.EnumType(values=None) | AST.StructType(fields=None) | AST.UnionType(fields=None):
                return symbol.ctype
    match ctype:
        case AST.StructType(fields=[*fields]) | AST.UnionType(fields=[*fields]):
            return ctype._replace(fields=[_resolve_field(field, scopes) for field in fields])
        case AST.EnumType(values=[*values]):
            return ctype._replace(values=[_resolve_enumerator(value, scopes) for value in values])
    return ctype


def _resolve_initializer(init: AST.Initializer, scopes: list[AST.Scope]) -> AST.Initializer:
    match init:
        case AST.InitList():
            return init._replace(items=[_resolve_initializer_item(item, scopes) for item in init.items])
    return _resolve_expr(init, scopes)


def _resolve_initializer_item(item: AST.InitializerItem, scopes: list[AST.Scope]) -> AST.InitializerItem:
    designators = [d._replace(index=_resolve_expr(d.index, scopes)) if d.index else d for d in item.designators]
    return item._replace(designators=designators, value=_resolve_initializer(item.value, scopes))


def _resolve_expr(expr: AST.Expr, scopes: list[AST.Scope]) -> AST.Expr:
    match expr:
        case AST.Assign(target=target, value=value):
            target = _resolve_expr(target, scopes)
            value = _resolve_expr(value, scopes)
            return expr._replace(target=target, value=value)
        case AST.Binary(left=left, right=right):
            left = _resolve_expr(left, scopes)
            right = _resolve_expr(right, scopes)
            return expr._replace(left=left, right=right)
        case AST.Unary(value=value):
            value = _resolve_expr(value, scopes)
            return expr._replace(value=value)
        case AST.IncDec(value=value):
            value = _resolve_expr(value, scopes)
            return expr._replace(value=value)
        case AST.Call(func=func, args=args):
            func = _resolve_expr(func, scopes)
            args = [_resolve_expr(arg, scopes) for arg in args]
            return expr._replace(func=func, args=args)
        case AST.Member(value=value):
            value = _resolve_expr(value, scopes)
            return expr._replace(value=value)
        case AST.Conditional(cond=cond, then=then, otherwise=otherwise):
            cond = _resolve_expr(cond, scopes)
            then = _resolve_expr(then, scopes)
            otherwise = _resolve_expr(otherwise, scopes)
            return expr._replace(cond=cond, then=then, otherwise=otherwise)
        case AST.Cast(target_type=target_type, value=value):
            target_type = _resolve_ctype(target_type, scopes)
            value = _resolve_expr(value, scopes)
            return expr._replace(target_type=target_type, value=value)
        case AST.Sizeof(value=value) if isinstance(value, AST.CType):
            value = _resolve_ctype(value, scopes)
            return expr._replace(value=value)
        case AST.Sizeof(value=value):
            value = _resolve_expr(value, scopes)
            return expr._replace(value=value)
        case AST.CompoundLiteral(ctype=ctype, value=value):
            ctype = _resolve_ctype(ctype, scopes)
            value = _resolve_initializer(value, scopes)
            return expr._replace(ctype=ctype, value=value)
        case AST.IntLiteral() | AST.BoolLiteral() | AST.FloatLiteral() | AST.CharLiteral() | AST.StringLiteral() | AST.Identifier():
            return expr
    raise TypeError(f"Unknown expr: {type(expr).__name__}")


def _lookup_tag(scopes: list[AST.Scope], name: str) -> AST.Symbol | None:
    for scope in reversed(scopes):
        if symbol := scope.tags.get(name):
            return symbol
    return None


def _resolve_const_int(expr: AST.Expr | None, scopes: list[AST.Scope], error_message: str) -> AST.IntLiteral | None:
    if expr is None:
        return None
    resolved = _resolve_expr(expr, scopes)
    value = const_eval(resolved)
    if value is None:
        error(resolved.span, error_message)
    return AST.IntLiteral(value, span=resolved.span)
