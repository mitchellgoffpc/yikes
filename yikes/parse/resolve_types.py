from __future__ import annotations

from typing import NoReturn

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.helpers import const_eval


def resolve_types(program: AST.Program) -> AST.Program:
    scopes: list[AST.Scope] = [program.scope]
    items = [_resolve_external_decl(item, scopes) for item in program.items]
    return program._replace(items=items)


def _resolve_external_decl(node: AST.ExternalDecl, scopes: list[AST.Scope]) -> AST.ExternalDecl:
    match node:
        case AST.FunctionDef():
            return _resolve_function_def(node, scopes)
        case AST.VarDecl():
            resolved = _resolve_ctype(node.ctype, scopes)
            init = _resolve_initializer(node.init, scopes) if node.init else None
            _set_symbol_ctype(scopes[-1], node.name, resolved)
            return node._replace(ctype=resolved, init=init)
        case AST.TypeDef():
            resolved = _resolve_ctype(node.ctype, scopes)
            _set_symbol_ctype(scopes[-1], node.name, resolved)
            return node._replace(ctype=resolved)
        case AST.StructDef():
            resolved = _resolve_struct_def(node.ctype, scopes)
            return node._replace(ctype=resolved)
        case AST.UnionDef():
            resolved = _resolve_union_def(node.ctype, scopes)
            return node._replace(ctype=resolved)
        case AST.EnumDef():
            resolved = _resolve_enum_def(node.ctype, scopes)
            return node._replace(ctype=resolved)
        case _:
            raise TypeError(f"Unknown external decl: {type(node).__name__}")


def _resolve_stmt(node: AST.Stmt, scopes: list[AST.Scope]) -> AST.Stmt:
    match node:
        case AST.Block():
            return _resolve_block(node, scopes)
        case AST.VarDecl():
            resolved = _resolve_ctype(node.ctype, scopes)
            init = _resolve_initializer(node.init, scopes) if node.init else None
            _set_symbol_ctype(scopes[-1], node.name, resolved)
            return node._replace(ctype=resolved, init=init)
        case AST.TypeDef():
            resolved = _resolve_ctype(node.ctype, scopes)
            _set_symbol_ctype(scopes[-1], node.name, resolved)
            return node._replace(ctype=resolved)
        case AST.StructDef():
            resolved = _resolve_struct_def(node.ctype, scopes)
            return node._replace(ctype=resolved)
        case AST.UnionDef():
            resolved = _resolve_union_def(node.ctype, scopes)
            return node._replace(ctype=resolved)
        case AST.EnumDef():
            resolved = _resolve_enum_def(node.ctype, scopes)
            return node._replace(ctype=resolved)
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
        case _:
            raise TypeError(f"Unknown stmt: {type(node).__name__}")


def _resolve_block(block: AST.Block, scopes: list[AST.Scope]) -> AST.Block:
    block_scopes = [*scopes, block.scope]
    items = [_resolve_stmt(item, block_scopes) for item in block.items]
    return block._replace(items=items)


def _resolve_function_def(node: AST.FunctionDef, scopes: list[AST.Scope]) -> AST.FunctionDef:
    resolved_ctype = _resolve_ctype(node.ctype, scopes)
    resolved_ctype = _ensure_function_type(resolved_ctype, node.name.span)
    _set_symbol_ctype(scopes[-1], node.name, resolved_ctype)
    function_scopes = [*scopes, node.body.scope]
    for param in resolved_ctype.params:
        if param.name:
            _set_symbol_ctype(function_scopes[-1], param.name, param.ctype)
    body = _resolve_block(node.body, function_scopes)
    return node._replace(ctype=resolved_ctype, body=body)


def _resolve_param(param: AST.Param, scopes: list[AST.Scope]) -> AST.Param:
    return AST.Param(param.name, _resolve_ctype(param.ctype, scopes))


def _resolve_struct_def(ctype: AST.StructType, scopes: list[AST.Scope]) -> AST.StructType:
    match ctype:
        case AST.StructType(name=name, fields=[*fields]):
            resolved_fields = [_resolve_field(field, scopes) for field in fields]
            resolved = AST.StructType(name, resolved_fields)
            if name:
                _set_tag_ctype(scopes[-1], name, resolved)
            return resolved
    return ctype


def _resolve_union_def(ctype: AST.UnionType, scopes: list[AST.Scope]) -> AST.UnionType:
    match ctype:
        case AST.UnionType(name=name, fields=[*fields]):
            resolved_fields = [_resolve_field(field, scopes) for field in fields]
            resolved = AST.UnionType(name, resolved_fields)
            if name:
                _set_tag_ctype(scopes[-1], name, resolved)
            return resolved
    return ctype


def _resolve_enum_def(ctype: AST.EnumType, scopes: list[AST.Scope]) -> AST.EnumType:
    match ctype:
        case AST.EnumType(name=name, values=[*values]):
            resolved_values = [_resolve_enumerator(value, scopes) for value in values]
            resolved = AST.EnumType(name, resolved_values)
            if name:
                _set_tag_ctype(scopes[-1], name, resolved)
            return resolved
    return ctype


def _resolve_enumerator(value: AST.Enumerator, scopes: list[AST.Scope]) -> AST.Enumerator:
    if value.value is None:
        return value
    expr = _resolve_expr(value.value, scopes)
    const_value = const_eval(expr)
    if const_value is None:
        _error(expr.span, "Enumerator value is not a constant expression")
    return value._replace(value=AST.IntLiteral(const_value, span=expr.span))


def _resolve_field(field: AST.Field, scopes: list[AST.Scope]) -> AST.Field:
    bit_width = _resolve_bit_width(field.bit_width, scopes)
    ctype = _resolve_ctype(field.ctype, scopes)
    _ensure_field_type(ctype, field.span)
    return AST.Field(field.name, ctype, bit_width)


def _resolve_bit_width(bit_width: AST.Expr | None, scopes: list[AST.Scope]) -> AST.Expr | None:
    if bit_width is None:
        return None
    resolved = _resolve_expr(bit_width, scopes)
    value = const_eval(resolved)
    if value is None:
        _error(resolved.span, "Bit-field width is not a constant expression")
    return AST.IntLiteral(value, span=resolved.span)


def _resolve_ctype(ctype: AST.CType, scopes: list[AST.Scope], seen: set[str] | None = None) -> AST.CType:
    match ctype:
        case AST.BuiltinType():
            return ctype
        case AST.NamedType(name=name):
            return _resolve_named_type(name, scopes, seen)
        case AST.PointerType():
            return AST.PointerType(_resolve_ctype(ctype.base, scopes, seen))
        case AST.ArrayType():
            base = _resolve_ctype(ctype.base, scopes, seen)
            size = _resolve_array_size(ctype.size, scopes)
            return AST.ArrayType(base, size)
        case AST.FunctionType():
            resolved = AST.FunctionType(
                _resolve_ctype(ctype.return_type, scopes, seen),
                [_resolve_param(param, scopes) for param in ctype.params],
                ctype.variadic,
            )
            return _ensure_function_type(resolved, ctype.span)
        case AST.StructType() | AST.UnionType() | AST.EnumType():
            return _resolve_tag_type(ctype, scopes)
        case _:
            raise TypeError(f"Unknown ctype: {type(ctype).__name__}")


def _resolve_array_size(size: AST.Expr | None, scopes: list[AST.Scope]) -> AST.Expr | None:
    if size is None:
        return None
    resolved = _resolve_expr(size, scopes)
    value = const_eval(resolved)
    if value is None:
        _error(resolved.span, "Array size is not a constant expression")
    return AST.IntLiteral(value, span=resolved.span)


def _resolve_named_type(name: AST.Identifier, scopes: list[AST.Scope], seen: set[str] | None) -> AST.CType:
    if seen is None:
        seen = set()
    if name.name in seen:
        _error(name.span, f"Typedef cycle for '{name.name}'")
    seen.add(name.name)
    match _lookup_ident(scopes, name.name):
        case AST.Symbol(kind=AST.SymbolKind.TYPEDEF, ctype=ctype) if ctype:
            return _resolve_ctype(ctype, scopes, seen)
    _error(name.span, f"Unknown type name '{name.name}'")


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
    if isinstance(init, AST.InitList):
        items = [_resolve_initializer_item(item, scopes) for item in init.items]
        return init._replace(items=items)
    return _resolve_expr(init, scopes)


def _resolve_initializer_item(item: AST.InitializerItem, scopes: list[AST.Scope]) -> AST.InitializerItem:
    designators: list[AST.Designator] = []
    for designator in item.designators:
        if designator.index:
            designators.append(designator._replace(index=_resolve_expr(designator.index, scopes)))
        else:
            designators.append(designator)
    value = _resolve_initializer(item.value, scopes)
    return item._replace(designators=designators, value=value)


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


def _ensure_function_type(ctype: AST.CType, span: AST.Span | None) -> AST.FunctionType:
    if not isinstance(ctype, AST.FunctionType):
        _error(span, "Function type required")
    if _is_array(ctype.return_type) or _is_function(ctype.return_type):
        _error(span, "Function cannot return array or function type")
    return ctype


def _ensure_field_type(ctype: AST.CType, span: AST.Span | None) -> None:
    if _is_void(ctype) or _is_function(ctype) or not _is_complete(ctype):
        _error(span, "Invalid field type")


def _is_void(ctype: AST.CType) -> bool:
    return isinstance(ctype, AST.BuiltinType) and any(kw.name == "void" for kw in ctype.keywords)


def _is_array(ctype: AST.CType) -> bool:
    return isinstance(ctype, AST.ArrayType)


def _is_function(ctype: AST.CType) -> bool:
    return isinstance(ctype, AST.FunctionType)


def _is_complete(ctype: AST.CType) -> bool:
    match ctype:
        case AST.BuiltinType():
            return not _is_void(ctype)
        case AST.PointerType():
            return True
        case AST.ArrayType(base=base, size=size):
            return size is not None and _is_complete(base)
        case AST.FunctionType():
            return False
        case AST.StructType(fields=fields) | AST.UnionType(fields=fields):
            return fields is not None and all(_is_complete(field.ctype) for field in fields)
        case AST.EnumType():
            return True
        case AST.NamedType():
            return False
    return False


def _lookup_ident(scopes: list[AST.Scope], name: str) -> AST.Symbol | None:
    for scope in reversed(scopes):
        if symbol := scope.idents.get(name):
            return symbol
    return None


def _lookup_tag(scopes: list[AST.Scope], name: str) -> AST.Symbol | None:
    for scope in reversed(scopes):
        if symbol := scope.tags.get(name):
            return symbol
    return None


def _set_symbol_ctype(scope: AST.Scope, name: AST.Identifier, ctype: AST.CType) -> None:
    if symbol := scope.idents.get(name.name):
        symbol.ctype = ctype


def _set_tag_ctype(scope: AST.Scope, name: AST.Identifier, ctype: AST.CType) -> None:
    if symbol := scope.tags.get(name.name):
        symbol.ctype = ctype


def _error(span: AST.Span | None, message: str) -> NoReturn:
    assert span is not None
    raise ValueError(f"{message} at {span.start.line}:{span.start.col}")
