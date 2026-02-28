from __future__ import annotations

from dataclasses import dataclass

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.helpers import const_eval, error, is_complete, lookup_ident


@dataclass
class TypeContext:
    return_type: AST.CType

def check_types(program: AST.Program) -> AST.Program:
    scopes = [program.scope]
    items = [_check_external_decl(item, scopes) for item in program.items]
    return program._replace(items=items)

def _check_external_decl(node: AST.ExternalDecl, scopes: list[AST.Scope]) -> AST.ExternalDecl:
    match node:
        case AST.FunctionDef():
            func_type = _ensure_function_type(node.ctype, node.name.span)
            ctx = TypeContext(func_type.return_type)
            body = _check_block(node.body, scopes, ctx)
            return node._replace(ctype=func_type, body=body)
        case AST.VarDecl():
            return _check_var_decl(node, scopes)
        case AST.TypeDef() | AST.StructDef() | AST.UnionDef() | AST.EnumDef():
            return node

def _check_stmt(node: AST.Stmt, scopes: list[AST.Scope], ctx: TypeContext) -> AST.Stmt:
    match node:
        case AST.Block():
            return _check_block(node, scopes, ctx)
        case AST.VarDecl():
            return _check_var_decl(node, scopes)
        case AST.TypeDef() | AST.StructDef() | AST.UnionDef() | AST.EnumDef():
            return node
        case AST.ExprStmt(expr=expr):
            expr = _check_expr(expr, scopes) if expr else None
            return node._replace(expr=expr)
        case AST.Return(value=value):
            if value is None:
                _ensure_void(ctx.return_type, node.span)
                return node
            value = _check_expr(value, scopes)
            _ensure_assignable(ctx.return_type, value, node.span)
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
            body = _check_block(body, scopes, ctx)
            return node._replace(cond=cond, body=body)
        case AST.Break() | AST.Continue():
            return node
        case AST.Switch(expr=expr, body=body):
            expr = _check_expr(expr, scopes)
            _ensure_integer(_expr_type(expr), expr.span)
            body = _check_block(body, scopes, ctx)
            return node._replace(expr=expr, body=body)
        case AST.Case(value=value, body=body):
            value = _check_expr(value, scopes)
            _ensure_integer(_expr_type(value), value.span)
            body = _check_block(body, scopes, ctx)
            return node._replace(value=value, body=body)
        case AST.Default(body=body):
            body = _check_block(body, scopes, ctx)
            return node._replace(body=body)
        case AST.Label(stmt=stmt):
            stmt = _check_stmt(stmt, scopes, ctx)
            return node._replace(stmt=stmt)
        case AST.Goto():
            return node

def _check_block(block: AST.Block, scopes: list[AST.Scope], ctx: TypeContext) -> AST.Block:
    block_scopes = [*scopes, block.scope]
    items = [_check_stmt(item, block_scopes, ctx) for item in block.items]
    return block._replace(items=items, scope=block.scope)

def _check_var_decl(node: AST.VarDecl, scopes: list[AST.Scope]) -> AST.VarDecl:
    _ensure_object_type(node.ctype, node.name.span)
    init = _check_initializer(node.init, node.ctype, scopes) if node.init else None
    return node._replace(init=init)

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
            symbol = lookup_ident(scopes, expr.name)
            if symbol is None:
                error(expr.span, f"Unknown identifier '{expr.name}'")
            if symbol.kind == AST.SymbolKind.TYPEDEF:
                error(expr.span, f"'{expr.name}' is a typedef")
            if symbol.kind == AST.SymbolKind.ENUM_CONST:
                return expr._replace(expr_type=_int_type())
            if symbol.ctype is None:
                error(expr.span, f"'{expr.name}' has unknown type")
            return expr._replace(expr_type=symbol.ctype)
        case AST.Assign(target=target, value=value):
            target = _check_expr(target, scopes)
            value = _check_expr(value, scopes)
            _ensure_modifiable_lvalue(target)
            _ensure_assignable(_expr_type(target), value, expr.span)
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

def _check_initializer(init: AST.Initializer, target: AST.CType, scopes: list[AST.Scope]) -> AST.Initializer:
    if isinstance(init, AST.InitList):
        match target:
            case AST.ArrayType():
                items = _check_init_list_array(init, target, scopes)
                return init._replace(items=items)
            case AST.StructType() | AST.UnionType():
                items = _check_init_list_struct(init, target, scopes)
                return init._replace(items=items)
        error(init.span, "Initializer list used for non-aggregate type")
    expr = _check_expr(init, scopes)
    _ensure_assignable(target, expr, expr.span)
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
        error(init.span, "Initializer for incomplete type")
    field_iter = iter(target.fields or [])
    items: list[AST.InitializerItem] = []
    for item in init.items:
        designators = [_check_designator(d, scopes) for d in item.designators]
        field = _designated_field(target, designators[0]) if designators else next(field_iter, None)
        if field is None:
            error(item.span, "Too many initializers")
        value = _check_initializer(item.value, field.ctype, scopes)
        items.append(item._replace(designators=designators, value=value))
    return items

def _check_designator(designator: AST.Designator, scopes: list[AST.Scope]) -> AST.Designator:
    if designator.index:
        index = _check_expr(designator.index, scopes)
        _ensure_integer(_expr_type(index), index.span)
        if const_eval(index) is None:
            error(index.span, "Array designator is not a constant expression")
        return designator._replace(index=index)
    return designator

def _designated_field(target: AST.StructType | AST.UnionType, designator: AST.Designator) -> AST.Field | None:
    if designator.field is None:
        return None
    for struct_field in target.fields or []:
        if struct_field.name and struct_field.name.name == designator.field.name:
            return struct_field
    error(designator.span, f"Unknown field '{designator.field.name}'")

def _expr_type(expr: AST.Expr) -> AST.CType:
    if expr.expr_type is None:
        error(expr.span, "Expression type missing")
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
    error(span, f"Unknown binary operator '{op}'")

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
    error(span, f"Unknown unary operator '{op}'")

def _call_type(func: AST.Expr, args: list[AST.Expr], span: AST.Span | None) -> AST.CType:
    func_type = _rvalue_type(_expr_type(func))
    if isinstance(func_type, AST.PointerType):
        func_type = func_type.base
    if not isinstance(func_type, AST.FunctionType):
        error(span, "Called object is not a function")
    if func_type.variadic:
        if len(args) < len(func_type.params):
            error(span, "Not enough arguments for variadic function")
    elif len(args) != len(func_type.params):
        error(span, "Incorrect argument count")
    for arg, param in zip(args, func_type.params, strict=False):
        param_type = _rvalue_type(param.ctype)
        _ensure_assignable(param_type, arg, arg.span)
    return func_type.return_type

def _member_type(value: AST.Expr, name: AST.Identifier, through_pointer: bool, span: AST.Span | None) -> AST.CType:
    ctype = _expr_type(value)
    if through_pointer:
        rvalue = _rvalue_type(ctype)
        if not isinstance(rvalue, AST.PointerType):
            error(span, "Member access through non-pointer")
        ctype = rvalue.base
    if not isinstance(ctype, AST.StructType | AST.UnionType):
        error(span, "Member access on non-struct/union")
    if ctype.fields is None:
        error(span, "Member access on incomplete type")
    for struct_field in ctype.fields:
        if struct_field.name and struct_field.name.name == name.name:
            return struct_field.ctype
    error(name.span, f"Unknown field '{name.name}'")

def _conditional_type(then: AST.Expr, otherwise: AST.Expr, span: AST.Span | None) -> AST.CType:
    then_type = _rvalue_type(_expr_type(then))
    otherwise_type = _rvalue_type(_expr_type(otherwise))
    if _type_key(then_type) == _type_key(otherwise_type):
        return then_type
    if _is_arithmetic(then_type) and _is_arithmetic(otherwise_type):
        return _usual_arithmetic(then_type, otherwise_type)
    match (then_type, otherwise_type):
        case (AST.PointerType(), AST.PointerType()) if _compatible_pointer(then_type, otherwise_type):
            return then_type
        case (AST.PointerType(), AST.IntLiteral(value=0)):
            return then_type
        case (AST.IntLiteral(value=0), AST.PointerType()):
            return otherwise_type
    error(span, "Incompatible types in conditional expression")

def _add_sub_type(op: str, left: AST.Expr, right: AST.Expr, span: AST.Span | None) -> AST.CType:
    left_type = _rvalue_type(_expr_type(left))
    right_type = _rvalue_type(_expr_type(right))
    if isinstance(left_type, AST.PointerType) and _is_integer(right_type):
        return left_type
    if _is_integer(left_type) and isinstance(right_type, AST.PointerType) and op == "+":
        return right_type
    if isinstance(left_type, AST.PointerType) and isinstance(right_type, AST.PointerType) and op == "-":
        if _compatible_pointer(left_type, right_type):
            return _int_type()
        error(span, "Pointer subtraction with incompatible types")
    _ensure_arithmetic(left_type, left.span)
    _ensure_arithmetic(right_type, right.span)
    return _usual_arithmetic(left_type, right_type)

def _deref_type(ctype: AST.CType, span: AST.Span | None) -> AST.CType:
    match _rvalue_type(ctype):
        case AST.PointerType(base=base):
            return base
    error(span, "Cannot dereference non-pointer")

def _rvalue_type(ctype: AST.CType) -> AST.CType:
    match ctype:
        case AST.ArrayType(base=base):
            return AST.PointerType(base)
        case AST.FunctionType():
            return AST.PointerType(ctype)
    return ctype

def _ensure_object_type(ctype: AST.CType, span: AST.Span | None) -> None:
    if isinstance(ctype, (AST.VoidType, AST.FunctionType)):
        error(span, "Object type required")
    if not is_complete(ctype):
        error(span, "Incomplete object type")

def _ensure_function_type(ctype: AST.CType, span: AST.Span | None) -> AST.FunctionType:
    match ctype:
        case AST.FunctionType():
            if isinstance(ctype.return_type, (AST.ArrayType, AST.FunctionType)):
                error(span, "Function cannot return array or function type")
            return ctype
    error(span, "Function type required")

def _ensure_assignable(target: AST.CType, value: AST.Expr, span: AST.Span | None) -> None:
    target = _rvalue_type(target)
    value_type = _rvalue_type(_expr_type(value))
    if _is_arithmetic(target) and _is_arithmetic(value_type):
        return
    match (target, value):
        case AST.PointerType(), AST.PointerType() if _compatible_pointer(target, value_type):
            return
        case AST.PointerType(), AST.IntLiteral(value=0):
            return
    error(span, "Incompatible types in assignment")

def _ensure_castable(ctype: AST.CType, span: AST.Span | None) -> None:
    if isinstance(ctype, AST.FunctionType):
        error(span, "Cannot cast to function type")
    if not is_complete(ctype):
        error(span, "Cannot cast to incomplete type")

def _ensure_sizeof_type(ctype: AST.CType, span: AST.Span | None) -> None:
    if isinstance(ctype, AST.FunctionType) or not is_complete(ctype):
        error(span, "Invalid sizeof operand")

def _ensure_lvalue(expr: AST.Expr) -> None:
    if not _is_lvalue(expr):
        error(expr.span, "Expected lvalue")

def _ensure_modifiable_lvalue(expr: AST.Expr) -> None:
    _ensure_lvalue(expr)
    if isinstance(_expr_type(expr), (AST.ArrayType, AST.FunctionType)):
        error(expr.span, "Expected modifiable lvalue")

def _ensure_integer(ctype: AST.CType, span: AST.Span | None) -> None:
    if not _is_integer(ctype):
        error(span, "Expected integer type")

def _ensure_arithmetic(ctype: AST.CType, span: AST.Span | None) -> None:
    if not _is_arithmetic(ctype):
        error(span, "Expected arithmetic type")

def _ensure_scalar(ctype: AST.CType, span: AST.Span | None) -> None:
    if not _is_scalar(ctype):
        error(span, "Expected scalar type")

def _ensure_void(ctype: AST.CType, span: AST.Span | None) -> None:
    if not isinstance(ctype, AST.VoidType):
        error(span, "Expected void return")

def _ensure_comparable(left: AST.CType, right: AST.CType, span: AST.Span | None) -> None:
    left = _rvalue_type(left)
    right = _rvalue_type(right)
    if _is_arithmetic(left) and _is_arithmetic(right):
        return
    if isinstance(left, AST.PointerType) and isinstance(right, AST.PointerType) and _compatible_pointer(left, right):
        return
    error(span, "Incompatible types for comparison")

def _is_lvalue(expr: AST.Expr) -> bool:
    match expr:
        case AST.Identifier() | AST.Member() | AST.StringLiteral() | AST.Unary(op="*"):
            return True
    return False

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
    return _is_arithmetic(ctype) or isinstance(ctype, AST.PointerType)

def _compatible_pointer(left: AST.CType, right: AST.CType) -> bool:
    match left, right:
        case AST.PointerType(base=left_base), AST.PointerType(base=right_base):
            return isinstance(left_base, AST.VoidType) or isinstance(right_base, AST.VoidType) or _type_key(left_base) == _type_key(right_base)
    return False

def _type_key(ctype: AST.CType) -> tuple:
    match ctype:
        case AST.BuiltinType(keywords=keywords):
            return ("builtin", tuple(sorted(kw.name for kw in keywords)))
        case AST.VoidType():
            return ("void",)
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
