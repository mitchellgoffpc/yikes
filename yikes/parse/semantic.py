from __future__ import annotations

from dataclasses import dataclass, field
from typing import NoReturn

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.helpers import const_eval


@dataclass
class SwitchContext:
    cases: set[int] = field(default_factory=set)
    has_default: bool = False


@dataclass
class FuncContext:
    return_type: AST.CType
    label_scope: AST.Scope
    loop_depth: int = 0
    switch_stack: list[SwitchContext] = field(default_factory=list)


def semantic(program: AST.Program) -> AST.Program:
    scopes = [program.scope]
    items = [_check_external_decl(item, scopes) for item in program.items]
    return program._replace(items=items)


def _check_external_decl(node: AST.ExternalDecl, scopes: list[AST.Scope]) -> AST.ExternalDecl:
    match node:
        case AST.FunctionDef():
            func_type = _ensure_function_type(node.ctype, node.name.span)
            ctx = FuncContext(func_type.return_type, node.scope)
            body = _check_block(node.body, scopes, ctx)
            return node._replace(ctype=func_type, body=body)
        case AST.VarDecl():
            _ensure_object_type(node.ctype, node.name.span)
            init = _check_initializer(node.init, node.ctype, scopes) if node.init else None
            return node._replace(init=init)
        case AST.TypeDef() | AST.StructDef() | AST.UnionDef() | AST.EnumDef():
            return node
    raise TypeError(f"Unknown external decl: {type(node).__name__}")


def _check_stmt(node: AST.Stmt, scopes: list[AST.Scope], ctx: FuncContext) -> AST.Stmt:
    match node:
        case AST.Block():
            return _check_block(node, scopes, ctx)
        case AST.VarDecl():
            _ensure_object_type(node.ctype, node.name.span)
            init = _check_initializer(node.init, node.ctype, scopes) if node.init else None
            return node._replace(init=init)
        case AST.TypeDef():
            return node
        case AST.StructDef():
            return node
        case AST.UnionDef():
            return node
        case AST.EnumDef():
            return node
        case AST.ExprStmt(expr=expr):
            expr = _check_expr(expr, scopes) if expr else None
            return node._replace(expr=expr)
        case AST.Return(value=value):
            if value is None:
                _ensure_void(ctx.return_type, node.span)
                return node
            value = _check_expr(value, scopes)
            _ensure_assignable(ctx.return_type, value, _expr_type(value), node.span)
            return node._replace(value=value)
        case AST.If(cond=cond, then=then, otherwise=otherwise):
            cond = _check_expr(cond, scopes)
            _ensure_scalar(_expr_type(cond), cond.span)
            then = _check_block(then, scopes, ctx)
            otherwise = _check_block(otherwise, scopes, ctx) if otherwise else None
            return node._replace(cond=cond, then=then, otherwise=otherwise)
        case AST.While(cond=cond, body=body):
            cond = _check_expr(cond, scopes)
            _ensure_scalar(_expr_type(cond), cond.span)
            ctx.loop_depth += 1
            body = _check_block(body, scopes, ctx)
            ctx.loop_depth -= 1
            return node._replace(cond=cond, body=body)
        case AST.Break():
            if ctx.loop_depth == 0 and not ctx.switch_stack:
                _error(node.span, "break not within loop or switch")
            return node
        case AST.Continue():
            if ctx.loop_depth == 0:
                _error(node.span, "continue not within loop")
            return node
        case AST.Switch(expr=expr, body=body):
            expr = _check_expr(expr, scopes)
            _ensure_integer(_expr_type(expr), expr.span)
            ctx.switch_stack.append(SwitchContext())
            body = _check_block(body, scopes, ctx)
            ctx.switch_stack.pop()
            return node._replace(expr=expr, body=body)
        case AST.Case(value=value, body=body):
            if not ctx.switch_stack:
                _error(node.span, "case not within switch")
            value = _check_expr(value, scopes)
            _ensure_integer(_expr_type(value), value.span)
            const = const_eval(value)
            if const is None:
                _error(value.span, "case value is not an integer constant expression")
            assert const is not None
            switch = ctx.switch_stack[-1]
            if const in switch.cases:
                _error(value.span, "duplicate case value")
            switch.cases.add(const)
            body = _check_block(body, scopes, ctx)
            return node._replace(value=value, body=body)
        case AST.Default(body=body):
            if not ctx.switch_stack:
                _error(node.span, "default not within switch")
            switch = ctx.switch_stack[-1]
            if switch.has_default:
                _error(node.span, "duplicate default label")
            switch.has_default = True
            body = _check_block(body, scopes, ctx)
            return node._replace(body=body)
        case AST.Label(name=name, stmt=stmt):
            _ensure_label(ctx.label_scope, name)
            stmt = _check_stmt(stmt, scopes, ctx)
            return node._replace(stmt=stmt)
        case AST.Goto(target=target):
            _ensure_goto_target(ctx.label_scope, target)
            return node
    raise TypeError(f"Unknown stmt: {type(node).__name__}")


def _check_block(block: AST.Block, scopes: list[AST.Scope], ctx: FuncContext, *, use_existing: bool = False) -> AST.Block:
    block_scope = scopes[-1] if use_existing else block.scope
    block_scopes = [*scopes, block_scope]
    items = [_check_stmt(item, block_scopes, ctx) for item in block.items]
    return block._replace(items=items, scope=block_scope)


def _check_expr(expr: AST.Expr, scopes: list[AST.Scope]) -> AST.Expr:
    match expr:
        case AST.IntLiteral():
            return expr._replace(expr_type=_int_type())
        case AST.BoolLiteral():
            return expr._replace(expr_type=_bool_type())
        case AST.FloatLiteral():
            return expr._replace(expr_type=_float_type())
        case AST.CharLiteral():
            return expr._replace(expr_type=_char_type())
        case AST.StringLiteral():
            return expr._replace(expr_type=AST.ArrayType(_char_type(), None))
        case AST.Identifier():
            symbol = _lookup_ident(scopes, expr.name)
            if symbol is None:
                _error(expr.span, f"Unknown identifier '{expr.name}'")
            assert symbol is not None
            if symbol.kind == AST.SymbolKind.TYPEDEF:
                _error(expr.span, f"'{expr.name}' is a typedef")
            if symbol.kind == AST.SymbolKind.ENUM_CONST:
                return expr._replace(expr_type=_int_type())
            if symbol.ctype is None:
                _error(expr.span, f"'{expr.name}' has unknown type")
            return expr._replace(expr_type=symbol.ctype)
        case AST.Assign(target=target, value=value):
            target = _check_expr(target, scopes)
            value = _check_expr(value, scopes)
            _ensure_modifiable_lvalue(target)
            _ensure_assignable(_expr_type(target), value, _expr_type(value), expr.span)
            return expr._replace(target=target, value=value, expr_type=_rvalue_type(_expr_type(target)))
        case AST.Binary(op=op, left=left, right=right):
            left = _check_expr(left, scopes)
            right = _check_expr(right, scopes)
            expr_type = _binary_type(op, left, right, expr.span)
            return expr._replace(left=left, right=right, expr_type=expr_type)
        case AST.Unary(op=op, value=value):
            value = _check_expr(value, scopes)
            expr_type, _ = _unary_type(op, value, expr.span)
            return expr._replace(value=value, expr_type=expr_type)
        case AST.IncDec(op=op, value=value):
            value = _check_expr(value, scopes)
            _ensure_modifiable_lvalue(value)
            _ensure_scalar(_expr_type(value), value.span)
            return expr._replace(value=value, expr_type=_rvalue_type(_expr_type(value)))
        case AST.Call(func=func, args=args):
            func = _check_expr(func, scopes)
            args = [_check_expr(arg, scopes) for arg in args]
            result = _call_type(func, args, expr.span)
            return expr._replace(func=func, args=args, expr_type=result)
        case AST.Member(value=value, name=name, through_pointer=through_pointer):
            value = _check_expr(value, scopes)
            expr_type = _member_type(value, name, through_pointer, expr.span)
            return expr._replace(value=value, expr_type=expr_type)
        case AST.Conditional(cond=cond, then=then, otherwise=otherwise):
            cond = _check_expr(cond, scopes)
            _ensure_scalar(_expr_type(cond), cond.span)
            then = _check_expr(then, scopes)
            otherwise = _check_expr(otherwise, scopes)
            expr_type = _conditional_type(then, otherwise, expr.span)
            return expr._replace(cond=cond, then=then, otherwise=otherwise, expr_type=expr_type)
        case AST.Cast(target_type=target_type, value=value):
            value = _check_expr(value, scopes)
            _ensure_castable(target_type, expr.span)
            return expr._replace(target_type=target_type, value=value, expr_type=target_type)
        case AST.Sizeof(value=value) if isinstance(value, AST.CType):
            _ensure_sizeof_type(value, expr.span)
            return expr._replace(value=value, expr_type=_int_type())
        case AST.Sizeof(value=value):
            value = _check_expr(value, scopes)
            _ensure_sizeof_type(_expr_type(value), value.span)
            return expr._replace(value=value, expr_type=_int_type())
        case AST.CompoundLiteral(ctype=ctype, value=value):
            _ensure_object_type(ctype, expr.span)
            value = _check_initializer(value, ctype, scopes)
            return expr._replace(ctype=ctype, value=value, expr_type=ctype)
    raise TypeError(f"Unknown expr: {type(expr).__name__}")


def _check_initializer(init: AST.Initializer, target: AST.CType, scopes: list[AST.Scope]) -> AST.Initializer:
    if isinstance(init, AST.InitList):
        match target:
            case AST.ArrayType():
                items = _check_init_list_array(init, target, scopes)
                return init._replace(items=items)
            case AST.StructType() | AST.UnionType():
                items = _check_init_list_struct(init, target, scopes)
                return init._replace(items=items)
        _error(init.span, "Initializer list used for non-aggregate type")
    expr = _check_expr(init, scopes)
    _ensure_assignable(target, expr, _expr_type(expr), expr.span)
    return expr


def _check_init_list_array(init: AST.InitList, target: AST.ArrayType, scopes: list[AST.Scope]) -> list[AST.InitializerItem]:
    items: list[AST.InitializerItem] = []
    for item in init.items:
        designators = [_check_designator(d, scopes) for d in item.designators]
        value = _check_initializer(item.value, target.base, scopes)
        items.append(item._replace(designators=designators, value=value))
    return items


def _check_init_list_struct(init: AST.InitList, target: AST.StructType | AST.UnionType, scopes: list[AST.Scope]) -> list[AST.InitializerItem]:
    if target.fields is None:
        _error(init.span, "Initializer for incomplete type")
    field_iter = iter(target.fields or [])
    items: list[AST.InitializerItem] = []
    for item in init.items:
        designators = [_check_designator(d, scopes) for d in item.designators]
        field = _designated_field(target, designators[0]) if designators else next(field_iter, None)
        if field is None:
            _error(item.span, "Too many initializers")
        assert field is not None
        value = _check_initializer(item.value, field.ctype, scopes)
        items.append(item._replace(designators=designators, value=value))
    return items


def _check_designator(designator: AST.Designator, scopes: list[AST.Scope]) -> AST.Designator:
    if designator.index:
        index = _check_expr(designator.index, scopes)
        _ensure_integer(_expr_type(index), index.span)
        if const_eval(index) is None:
            _error(index.span, "Array designator is not a constant expression")
        return designator._replace(index=index)
    return designator


def _designated_field(target: AST.StructType | AST.UnionType, designator: AST.Designator) -> AST.Field | None:
    if designator.field is None:
        return None
    for struct_field in target.fields or []:
        if struct_field.name and struct_field.name.name == designator.field.name:
            return struct_field
    _error(designator.span, f"Unknown field '{designator.field.name}'")
    return None


def _expr_type(expr: AST.Expr) -> AST.CType:
    if expr.expr_type is None:
        _error(expr.span, "Expression type missing")
    assert expr.expr_type is not None
    return expr.expr_type


def _binary_type(op: str, left: AST.Expr, right: AST.Expr, span: AST.Span | None) -> AST.CType:
    if op == ",":
        return _expr_type(right)
    if op in {"||", "&&"}:
        _ensure_scalar(_expr_type(left), left.span)
        _ensure_scalar(_expr_type(right), right.span)
        return _bool_type()
    if op in {"|", "^", "&"}:
        _ensure_integer(_expr_type(left), left.span)
        _ensure_integer(_expr_type(right), right.span)
        return _usual_arithmetic(_expr_type(left), _expr_type(right))
    if op in {"<<", ">>"}:
        _ensure_integer(_expr_type(left), left.span)
        _ensure_integer(_expr_type(right), right.span)
        return _expr_type(left)
    if op in {"*", "/", "%"}:
        _ensure_arithmetic(_expr_type(left), left.span)
        _ensure_arithmetic(_expr_type(right), right.span)
        if op == "%":
            _ensure_integer(_expr_type(left), left.span)
            _ensure_integer(_expr_type(right), right.span)
        return _usual_arithmetic(_expr_type(left), _expr_type(right))
    if op in {"+", "-"}:
        return _add_sub_type(op, left, right, span)
    if op in {"<", ">", "<=", ">=", "==", "!="}:
        _ensure_comparable(_expr_type(left), _expr_type(right), span)
        return _bool_type()
    _error(span, f"Unknown binary operator '{op}'")
    return _int_type()


def _unary_type(op: str, value: AST.Expr, span: AST.Span | None) -> tuple[AST.CType, bool]:
    if op in {"+", "-"}:
        _ensure_arithmetic(_expr_type(value), value.span)
        return _rvalue_type(_expr_type(value)), False
    if op == "!":
        _ensure_scalar(_expr_type(value), value.span)
        return _bool_type(), False
    if op == "~":
        _ensure_integer(_expr_type(value), value.span)
        return _rvalue_type(_expr_type(value)), False
    if op == "*":
        base = _deref_type(_expr_type(value), value.span)
        return base, True
    if op == "&":
        _ensure_lvalue(value)
        return AST.PointerType(_expr_type(value)), False
    _error(span, f"Unknown unary operator '{op}'")
    return _int_type(), False


def _call_type(func: AST.Expr, args: list[AST.Expr], span: AST.Span | None) -> AST.CType:
    func_type = _rvalue_type(_expr_type(func))
    if isinstance(func_type, AST.PointerType):
        func_type = func_type.base
    if not isinstance(func_type, AST.FunctionType):
        _error(span, "Called object is not a function")
    if func_type.variadic:
        if len(args) < len(func_type.params):
            _error(span, "Not enough arguments for variadic function")
    elif len(args) != len(func_type.params):
        _error(span, "Incorrect argument count")
    for arg, param in zip(args, func_type.params, strict=False):
        param_type = _param_type(param.ctype)
        _ensure_assignable(param_type, arg, _expr_type(arg), arg.span)
    return func_type.return_type


def _member_type(value: AST.Expr, name: AST.Identifier, through_pointer: bool, span: AST.Span | None) -> AST.CType:
    ctype = _expr_type(value)
    if through_pointer:
        rvalue = _rvalue_type(ctype)
        if not isinstance(rvalue, AST.PointerType):
            _error(span, "Member access through non-pointer")
        ctype = rvalue.base
    if not isinstance(ctype, AST.StructType | AST.UnionType):
        _error(span, "Member access on non-struct/union")
    if ctype.fields is None:
        _error(span, "Member access on incomplete type")
    assert ctype.fields is not None
    for struct_field in ctype.fields:
        if struct_field.name and struct_field.name.name == name.name:
            return struct_field.ctype
    _error(name.span, f"Unknown field '{name.name}'")
    return _int_type()


def _conditional_type(then: AST.Expr, otherwise: AST.Expr, span: AST.Span | None) -> AST.CType:
    then_type = _rvalue_type(_expr_type(then))
    otherwise_type = _rvalue_type(_expr_type(otherwise))
    if _type_key(then_type) == _type_key(otherwise_type):
        return then_type
    if _is_arithmetic(then_type) and _is_arithmetic(otherwise_type):
        return _usual_arithmetic(then_type, otherwise_type)
    if _is_pointer(then_type) and _is_pointer(otherwise_type) and _compatible_pointer(then_type, otherwise_type):
        return then_type
    if _is_pointer(then_type) and _is_null_constant(otherwise):
        return then_type
    if _is_pointer(otherwise_type) and _is_null_constant(then):
        return otherwise_type
    _error(span, "Incompatible types in conditional expression")
    return then_type


def _add_sub_type(op: str, left: AST.Expr, right: AST.Expr, span: AST.Span | None) -> AST.CType:
    left_type = _rvalue_type(_expr_type(left))
    right_type = _rvalue_type(_expr_type(right))
    if _is_pointer(left_type) and _is_integer(right_type):
        return left_type
    if _is_integer(left_type) and _is_pointer(right_type) and op == "+":
        return right_type
    if _is_pointer(left_type) and _is_pointer(right_type) and op == "-":
        if _compatible_pointer(left_type, right_type):
            return _int_type()
        _error(span, "Pointer subtraction with incompatible types")
    _ensure_arithmetic(left_type, left.span)
    _ensure_arithmetic(right_type, right.span)
    return _usual_arithmetic(left_type, right_type)


def _deref_type(ctype: AST.CType, span: AST.Span | None) -> AST.CType:
    match _rvalue_type(ctype):
        case AST.PointerType(base=base):
            return base
    _error(span, "Cannot dereference non-pointer")
    return _int_type()


def _param_type(ctype: AST.CType) -> AST.CType:
    match ctype:
        case AST.ArrayType(base=base):
            return AST.PointerType(base)
        case AST.FunctionType():
            return AST.PointerType(ctype)
    return ctype


def _rvalue_type(ctype: AST.CType) -> AST.CType:
    match ctype:
        case AST.ArrayType(base=base):
            return AST.PointerType(base)
        case AST.FunctionType():
            return AST.PointerType(ctype)
    return ctype


def _ensure_object_type(ctype: AST.CType, span: AST.Span | None) -> None:
    if _is_void(ctype) or _is_function(ctype):
        _error(span, "Object type required")
    if not _is_complete(ctype):
        _error(span, "Incomplete object type")


def _ensure_function_type(ctype: AST.CType, span: AST.Span | None) -> AST.FunctionType:
    match ctype:
        case AST.FunctionType():
            if _is_array(ctype.return_type) or _is_function(ctype.return_type):
                _error(span, "Function cannot return array or function type")
            return ctype
    _error(span, "Function type required")
    return AST.FunctionType(_int_type(), [], False)


def _ensure_assignable(target: AST.CType, value: AST.Expr, value_type: AST.CType, span: AST.Span | None) -> None:
    target = _rvalue_type(target)
    value_type = _rvalue_type(value_type)
    if _is_arithmetic(target) and _is_arithmetic(value_type):
        return
    if _is_pointer(target) and _is_pointer(value_type) and _compatible_pointer(target, value_type):
        return
    if _is_pointer(target) and _is_null_constant(value):
        return
    _error(span, "Incompatible types in assignment")


def _ensure_castable(ctype: AST.CType, span: AST.Span | None) -> None:
    if _is_function(ctype):
        _error(span, "Cannot cast to function type")
    if not _is_complete(ctype):
        _error(span, "Cannot cast to incomplete type")


def _ensure_sizeof_type(ctype: AST.CType, span: AST.Span | None) -> None:
    if _is_function(ctype) or not _is_complete(ctype):
        _error(span, "Invalid sizeof operand")


def _ensure_lvalue(expr: AST.Expr) -> None:
    if not _is_lvalue(expr):
        _error(expr.span, "Expected lvalue")


def _ensure_modifiable_lvalue(expr: AST.Expr) -> None:
    _ensure_lvalue(expr)
    if _is_array(_expr_type(expr)) or _is_function(_expr_type(expr)):
        _error(expr.span, "Expected modifiable lvalue")


def _ensure_integer(ctype: AST.CType, span: AST.Span | None) -> None:
    if not _is_integer(ctype):
        _error(span, "Expected integer type")


def _ensure_arithmetic(ctype: AST.CType, span: AST.Span | None) -> None:
    if not _is_arithmetic(ctype):
        _error(span, "Expected arithmetic type")


def _ensure_scalar(ctype: AST.CType, span: AST.Span | None) -> None:
    if not _is_scalar(ctype):
        _error(span, "Expected scalar type")


def _ensure_void(ctype: AST.CType, span: AST.Span | None) -> None:
    if not _is_void(ctype):
        _error(span, "Expected void return")


def _ensure_comparable(left: AST.CType, right: AST.CType, span: AST.Span | None) -> None:
    left = _rvalue_type(left)
    right = _rvalue_type(right)
    if _is_arithmetic(left) and _is_arithmetic(right):
        return
    if _is_pointer(left) and _is_pointer(right) and _compatible_pointer(left, right):
        return
    _error(span, "Incompatible types for comparison")


def _is_lvalue(expr: AST.Expr) -> bool:
    match expr:
        case AST.Identifier() | AST.Member() | AST.StringLiteral() | AST.Unary(op="*"):
            return True
    return False


def _is_null_constant(expr: AST.Expr) -> bool:
    return isinstance(expr, AST.IntLiteral) and expr.value == 0


def _is_integer(ctype: AST.CType) -> bool:
    match ctype:
        case AST.EnumType():
            return True
        case AST.BuiltinType(keywords=keywords):
            names = {kw.name for kw in keywords}
            return bool(names & {"bool", "char", "short", "int", "long", "signed", "unsigned"})
    return False


def _is_floating(ctype: AST.CType) -> bool:
    match ctype:
        case AST.BuiltinType(keywords=keywords):
            names = {kw.name for kw in keywords}
            return bool(names & {"float", "double", "complex", "imaginary"})
    return False


def _is_arithmetic(ctype: AST.CType) -> bool:
    return _is_integer(ctype) or _is_floating(ctype)


def _is_scalar(ctype: AST.CType) -> bool:
    return _is_arithmetic(ctype) or _is_pointer(ctype)


def _is_void(ctype: AST.CType) -> bool:
    return isinstance(ctype, AST.BuiltinType) and any(kw.name == "void" for kw in ctype.keywords)


def _is_pointer(ctype: AST.CType) -> bool:
    return isinstance(ctype, AST.PointerType)


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


def _compatible_pointer(left: AST.CType, right: AST.CType) -> bool:
    match left, right:
        case AST.PointerType(base=left_base), AST.PointerType(base=right_base):
            return _is_void(left_base) or _is_void(right_base) or _type_key(left_base) == _type_key(right_base)
    return False


def _type_key(ctype: AST.CType) -> tuple:
    match ctype:
        case AST.BuiltinType(keywords=keywords):
            return ("builtin", tuple(sorted(kw.name for kw in keywords)))
        case AST.PointerType(base=base):
            return ("ptr", _type_key(base))
        case AST.ArrayType(base=base, size=size):
            size_val = const_eval(size) if isinstance(size, AST.Expr) else None
            return ("array", _type_key(base), size_val)
        case AST.FunctionType(return_type=return_type, params=params, variadic=variadic):
            return ("func", _type_key(return_type), tuple(_type_key(p.ctype) for p in params), variadic)
        case AST.StructType(name=name):
            return ("struct", name.name if name else id(ctype))
        case AST.UnionType(name=name):
            return ("union", name.name if name else id(ctype))
        case AST.EnumType(name=name):
            return ("enum", name.name if name else id(ctype))
        case AST.NamedType(name=name):
            return ("named", name.name)
    return ("unknown", id(ctype))


def _usual_arithmetic(left: AST.CType, right: AST.CType) -> AST.CType:
    if _is_floating(left) or _is_floating(right):
        if _is_double_type(left) or _is_double_type(right):
            return _double_type()
        return _float_type()
    return _int_type()


def _is_double_type(ctype: AST.CType) -> bool:
    return isinstance(ctype, AST.BuiltinType) and any(kw.name == "double" for kw in ctype.keywords)


def _int_type() -> AST.CType:
    return AST.BuiltinType([AST.TypeKeyword("int")])


def _bool_type() -> AST.CType:
    return AST.BuiltinType([AST.TypeKeyword("bool")])


def _char_type() -> AST.CType:
    return AST.BuiltinType([AST.TypeKeyword("char")])


def _float_type() -> AST.CType:
    return AST.BuiltinType([AST.TypeKeyword("float")])


def _double_type() -> AST.CType:
    return AST.BuiltinType([AST.TypeKeyword("double")])


def _lookup_ident(scopes: list[AST.Scope], name: str) -> AST.Symbol | None:
    for scope in reversed(scopes):
        if symbol := scope.idents.get(name):
            return symbol
    return None


def _ensure_label(scope: AST.Scope, name: AST.Identifier) -> None:
    if name.name not in scope.labels:
        _error(name.span, f"Unknown label '{name.name}'")


def _ensure_goto_target(scope: AST.Scope, name: AST.Identifier) -> None:
    if name.name not in scope.labels:
        _error(name.span, f"Unknown label '{name.name}'")


def _error(span: AST.Span | None, message: str) -> NoReturn:
    assert span is not None
    raise ValueError(f"{message} at {span.start.line}:{span.start.col}")
