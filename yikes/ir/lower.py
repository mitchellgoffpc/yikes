from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from yikes.ir import ir as IR  # noqa: N812
from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.helpers import const_eval, lookup_ident


@dataclass
class LoopContext:
    continue_target: IR.BasicBlock
    break_target: IR.BasicBlock


def lower(program: AST.Program) -> IR.Module:
    module = IR.Module([], [])
    value_id = 0
    block_id = 0
    string_id = 0
    blocks: list[IR.BasicBlock] = []
    current: IR.BasicBlock | None = None
    func: AST.FunctionDef | None = None
    scopes: list[AST.Scope] = []
    local_vars: list[dict[str, IR.Operand]] = []
    global_vars: dict[str, IR.Global] = {}
    functions: dict[str, IR.Value] = {}
    labels: dict[str, IR.BasicBlock] = {}
    loop_stack: list[LoopContext] = []
    switch_stack: list[IR.BasicBlock] = []
    strings: dict[str, IR.Global] = {}

    def collect_globals(program: AST.Program) -> None:
        for item in program.items:
            match item:
                case AST.FunctionDef():
                    func_type = lower_type(item.ctype)
                    func_ptr_type = IR.PointerType(func_type)
                    functions[item.name.name] = IR.Value(item.name.name, func_ptr_type)
                case AST.VarDecl():
                    add_global(item)

    def add_global(decl: AST.VarDecl) -> None:
        elem_type = lower_type(decl.ctype)
        global_type = IR.PointerType(elem_type)
        init = const_initializer(decl.init, decl.ctype) if decl.init else IR.ZeroInit(elem_type)
        global_var = IR.Global(decl.name.name, global_type, elem_type, init, False, None)
        global_vars[decl.name.name] = global_var
        module.globals.append(global_var)

    def lower_function(func_def: AST.FunctionDef) -> IR.Function:
        nonlocal func, blocks, current, labels, loop_stack, switch_stack, scopes, local_vars
        func = func_def
        blocks = []
        current = None
        labels = {}
        loop_stack = []
        switch_stack = []
        scopes = [func_def.scope, func_def.body.scope]
        local_vars = []

        func_type = cast(IR.FunctionType, lower_type(func_def.ctype))
        params = [IR.Param(param.name.name if param.name else f"param{idx}", param_type(param.ctype)) for idx, param in enumerate(func_def.ctype.params)]

        entry = new_block("entry")
        set_current(entry)
        push_scope()

        for param, param_ast in zip(params, func_def.ctype.params, strict=False):
            if param_ast.name is None:
                continue
            storage = emit(IR.Alloca(new_value(IR.PointerType(param.type), f"{param.name}.addr"), param.type))
            emit(IR.Store(storage, param))
            bind_local(param_ast.name.name, storage)

        lower_block(func_def.body)
        if current and current.term is None:
            if isinstance(func_def.ctype.return_type, AST.VoidType):
                set_term(IR.Ret(None))
            else:
                zero = zero_const(func_def.ctype.return_type)
                set_term(IR.Ret(zero))

        pop_scope()
        return IR.Function(func_def.name.name, func_type, params, blocks)

    def lower_block(block: AST.Block) -> None:
        scopes.append(block.scope)
        push_scope()
        for item in block.items:
            lower_stmt(item)
        pop_scope()
        scopes.pop()

    def lower_stmt(stmt: AST.Stmt) -> None:
        if current is None:
            return
        match stmt:
            case AST.Block():
                lower_block(stmt)
            case AST.VarDecl():
                lower_var_decl(stmt)
            case AST.TypeDef() | AST.StructDef() | AST.UnionDef() | AST.EnumDef():
                return
            case AST.ExprStmt(expr=expr):
                if expr:
                    lower_rvalue(expr)
            case AST.Return(value=value):
                if value is None:
                    set_term(IR.Ret(None))
                else:
                    assert func is not None
                    ret_value = coerce(lower_rvalue(value), expr_type(value), func.ctype.return_type)
                    set_term(IR.Ret(ret_value))
            case AST.If(cond=cond, then=then, otherwise=otherwise):
                lower_if(cond, then, otherwise)
            case AST.While(cond=cond, body=body):
                lower_while(cond, body)
            case AST.Break():
                if not loop_stack and not switch_stack:
                    return
                target = switch_stack[-1] if switch_stack else loop_stack[-1].break_target
                set_term(IR.Br(target))
            case AST.Continue():
                if not loop_stack:
                    return
                set_term(IR.Br(loop_stack[-1].continue_target))
            case AST.Switch(expr=expr, body=body):
                lower_switch(expr, body)
            case AST.Case() | AST.Default():
                return
            case AST.Label(name=name, stmt=inner):
                target = label_block(name.name)
                if current.term is None:
                    set_term(IR.Br(target))
                set_current(target)
                lower_stmt(inner)
            case AST.Goto(target=target):
                set_term(IR.Br(label_block(target.name)))

    def lower_if(cond: AST.Expr, then: AST.Block, otherwise: AST.Block | None) -> None:
        then_block = new_block("if.then")
        end_block = new_block("if.end")
        else_block = new_block("if.else") if otherwise else end_block

        cond_val = to_bool(lower_rvalue(cond), expr_type(cond))
        set_term(IR.CondBr(cond_val, then_block, else_block))

        set_current(then_block)
        lower_block(then)
        if current_block().term is None:
            set_term(IR.Br(end_block))

        if otherwise:
            set_current(else_block)
            lower_block(otherwise)
            if current_block().term is None:
                set_term(IR.Br(end_block))

        set_current(end_block)

    def lower_while(cond: AST.Expr, body: AST.Block) -> None:
        cond_block = new_block("while.cond")
        body_block = new_block("while.body")
        end_block = new_block("while.end")

        set_term(IR.Br(cond_block))

        set_current(cond_block)
        cond_val = to_bool(lower_rvalue(cond), expr_type(cond))
        set_term(IR.CondBr(cond_val, body_block, end_block))

        set_current(body_block)
        loop_stack.append(LoopContext(cond_block, end_block))
        lower_block(body)
        loop_stack.pop()
        if current_block().term is None:
            set_term(IR.Br(cond_block))

        set_current(end_block)

    def lower_switch(expr: AST.Expr, body: AST.Block) -> None:
        end_block = new_block("switch.end")
        default_block = None
        case_blocks: list[tuple[int, IR.BasicBlock]] = []
        ordered_labels: list[tuple[AST.Case | AST.Default, IR.BasicBlock]] = []

        switch_stack.append(end_block)

        for item in body.items:
            match item:
                case AST.Case(value=value):
                    const = const_eval(value)
                    if const is None:
                        continue
                    block = new_block("switch.case")
                    case_blocks.append((const, block))
                    ordered_labels.append((item, block))
                case AST.Default():
                    default_block = new_block("switch.default")
                    ordered_labels.append((item, default_block))

        if default_block is None:
            default_block = end_block

        switch_value = coerce(lower_rvalue(expr), expr_type(expr), int_type_ast())
        cases = [IR.SwitchCase(IR.IntConst(int_type(), value), block) for value, block in case_blocks]
        set_term(IR.Switch(switch_value, default_block, cases))

        ordered_blocks = [block for _, block in ordered_labels]
        for index, (item, target) in enumerate(ordered_labels):
            set_current(target)
            lower_block(item.body)
            if current_block().term is None:
                fallthrough = ordered_blocks[index + 1] if index + 1 < len(ordered_blocks) else end_block
                set_term(IR.Br(fallthrough))

        switch_stack.pop()
        set_current(end_block)

    def lower_var_decl(decl: AST.VarDecl) -> None:
        var_type = lower_type(decl.ctype)
        storage = emit(IR.Alloca(new_value(IR.PointerType(var_type), f"{decl.name.name}.addr"), var_type))
        bind_local(decl.name.name, storage)
        if decl.init:
            emit_initializer(storage, decl.ctype, decl.init)

    def lower_rvalue(expr: AST.Expr) -> IR.Operand:
        match expr:
            case AST.IntLiteral(value=value):
                return IR.IntConst(lower_type(expr_type(expr)), value)
            case AST.BoolLiteral(value=value):
                return IR.BoolConst(lower_type(expr_type(expr)), value)
            case AST.FloatLiteral(value=value):
                return IR.FloatConst(lower_type(expr_type(expr)), value)
            case AST.CharLiteral(value=value):
                return IR.CharConst(lower_type(expr_type(expr)), value)
            case AST.StringLiteral(value=value):
                return string_ptr(value)
            case AST.Identifier():
                return lower_identifier(expr)
            case AST.Assign(target=target, value=value):
                return lower_assign(target, value)
            case AST.Binary(op=op, left=left, right=right):
                return lower_binary(op, left, right, expr_type(expr))
            case AST.Unary(op=op, value=value):
                return lower_unary(op, value, expr_type(expr))
            case AST.IncDec(op=op, value=value, is_postfix=is_postfix):
                return lower_incdec(op, value, is_postfix)
            case AST.Call(func=func_expr, args=args):
                return lower_call(func_expr, args, expr_type(expr))
            case AST.Member():
                return load_lvalue(expr)
            case AST.Conditional(cond=cond, then=then, otherwise=otherwise):
                return lower_conditional(cond, then, otherwise, expr_type(expr))
            case AST.Cast(target_type=target_type, value=value):
                return coerce(lower_rvalue(value), expr_type(value), target_type)
            case AST.Sizeof(value=value):
                target = value if isinstance(value, AST.CType) else expr_type(value)
                return IR.IntConst(int_type(), sizeof(target))
            case AST.CompoundLiteral():
                return load_lvalue(expr)
        raise ValueError("Unknown expression")

    def load_lvalue(expr: AST.Expr) -> IR.Operand:
        ptr = lower_lvalue(expr)
        expr_ctype = expr_type(expr)
        if isinstance(expr_ctype, AST.ArrayType):
            return decay_array(ptr, expr_ctype)
        return emit(IR.Load(new_value(lower_type(expr_ctype), "load"), ptr))

    def lower_lvalue(expr: AST.Expr) -> IR.Operand:
        match expr:
            case AST.Identifier():
                return lower_ident_lvalue(expr)
            case AST.Unary(op="*", value=value):
                return lower_rvalue(value)
            case AST.Member(value=value, name=name, through_pointer=through_pointer):
                return lower_member_ptr(value, name, through_pointer)
            case AST.StringLiteral(value=value):
                return string_global(value)
            case AST.CompoundLiteral():
                return lower_compound_literal(expr)
        raise ValueError("Expression is not an lvalue")

    def lower_identifier(expr: AST.Identifier) -> IR.Operand:
        symbol = lookup_ident(scopes, expr.name)
        if symbol and symbol.kind == AST.SymbolKind.ENUM_CONST and isinstance(symbol.decl, AST.Enumerator):
            value = const_eval(symbol.decl.value) if symbol.decl.value else 0
            if value is None:
                value = 0
            return IR.IntConst(int_type(), value)
        if symbol and symbol.kind == AST.SymbolKind.FUNC:
            func_value = functions.get(expr.name)
            if func_value is None:
                assert symbol.ctype is not None
                func_type = lower_type(symbol.ctype)
                func_value = IR.Value(expr.name, IR.PointerType(func_type))
                functions[expr.name] = func_value
            return func_value
        return load_lvalue(expr)

    def lower_ident_lvalue(expr: AST.Identifier) -> IR.Operand:
        for scope in reversed(local_vars):
            if expr.name in scope:
                return scope[expr.name]
        if expr.name in global_vars:
            return global_vars[expr.name]
        raise ValueError(f"Unknown identifier '{expr.name}'")

    def lower_assign(target: AST.Expr, value: AST.Expr) -> IR.Operand:
        target_ptr = lower_lvalue(target)
        stored = coerce(lower_rvalue(value), expr_type(value), expr_type(target))
        emit(IR.Store(target_ptr, stored))
        return stored

    def lower_binary(op: str, left: AST.Expr, right: AST.Expr, result_type: AST.CType) -> IR.Operand:
        if op == ",":
            lower_rvalue(left)
            return lower_rvalue(right)
        if op in {"&&", "||"}:
            return lower_logical(op, left, right)
        if op in {"==", "!=", "<", "<=", ">", ">="}:
            return lower_cmp(op, left, right)
        left_val = lower_rvalue(left)
        right_val = lower_rvalue(right)
        if op in {"+", "-"} and (isinstance(expr_type(left), AST.PointerType) or isinstance(expr_type(right), AST.PointerType)):
            return lower_pointer_arith(op, left, right, left_val, right_val)
        left_val = coerce(left_val, expr_type(left), result_type)
        right_val = coerce(right_val, expr_type(right), result_type)
        binop = binop_kind(op)
        return emit(IR.BinOp(new_value(lower_type(result_type), "binop"), binop, left_val, right_val))

    def lower_cmp(op: str, left: AST.Expr, right: AST.Expr) -> IR.Operand:
        left_val = lower_rvalue(left)
        right_val = lower_rvalue(right)
        if is_float(expr_type(left)) or is_float(expr_type(right)):
            target = float_result_type(expr_type(left), expr_type(right))
            left_val = coerce(left_val, expr_type(left), target)
            right_val = coerce(right_val, expr_type(right), target)
            return emit(IR.FCmp(new_value(bool_type(), "fcmp"), cmp_kind(op), left_val, right_val))
        if isinstance(expr_type(left), AST.PointerType) and isinstance(expr_type(right), AST.PointerType):
            return emit(IR.ICmp(new_value(bool_type(), "icmp"), cmp_kind(op), left_val, right_val, False))
        left_val = coerce(left_val, expr_type(left), int_type_ast())
        right_val = coerce(right_val, expr_type(right), int_type_ast())
        signed = is_signed(expr_type(left)) and is_signed(expr_type(right))
        return emit(IR.ICmp(new_value(bool_type(), "icmp"), cmp_kind(op), left_val, right_val, signed))

    def lower_logical(op: str, left: AST.Expr, right: AST.Expr) -> IR.Operand:
        left_block = current_block()
        right_block = new_block("logic.rhs")
        end_block = new_block("logic.end")

        left_val = to_bool(lower_rvalue(left), expr_type(left))
        if op == "&&":
            set_term(IR.CondBr(left_val, right_block, end_block))
        else:
            set_term(IR.CondBr(left_val, end_block, right_block))

        set_current(right_block)
        right_val = to_bool(lower_rvalue(right), expr_type(right))
        set_term(IR.Br(end_block))

        set_current(end_block)
        phi = IR.Phi(new_value(bool_type(), "phi"), [(left_block, IR.BoolConst(bool_type(), op == "||")), (right_block, right_val)])
        current_block().phis.append(phi)
        return phi.result

    def lower_pointer_arith(op: str, left: AST.Expr, right: AST.Expr, left_val: IR.Operand, right_val: IR.Operand) -> IR.Operand:
        if isinstance(expr_type(left), AST.PointerType) and is_integer(expr_type(right)):
            index = coerce(right_val, expr_type(right), int_type_ast())
            if op == "-":
                index = emit(IR.BinOp(new_value(int_type(), "neg"), IR.BinOpKind.SUB, IR.IntConst(int_type(), 0), index))
            result_type = lower_type(expr_type(left))
            return emit(IR.Gep(new_value(result_type, "gep"), left_val, [index], result_type))
        if isinstance(expr_type(right), AST.PointerType) and is_integer(expr_type(left)) and op == "+":
            index = coerce(left_val, expr_type(left), int_type_ast())
            result_type = lower_type(expr_type(right))
            return emit(IR.Gep(new_value(result_type, "gep"), right_val, [index], result_type))
        raise ValueError("Unsupported pointer arithmetic")

    def lower_unary(op: str, value: AST.Expr, result_type: AST.CType) -> IR.Operand:
        match op:
            case "+":
                return coerce(lower_rvalue(value), expr_type(value), result_type)
            case "-":
                operand = coerce(lower_rvalue(value), expr_type(value), result_type)
                zero = zero_const(result_type)
                return emit(IR.BinOp(new_value(lower_type(result_type), "neg"), IR.BinOpKind.SUB, zero, operand))
            case "!":
                bool_val = to_bool(lower_rvalue(value), expr_type(value))
                return emit(IR.ICmp(new_value(bool_type(), "not"), IR.CmpKind.EQ, bool_val, IR.BoolConst(bool_type(), False), False))
            case "~":
                operand = coerce(lower_rvalue(value), expr_type(value), result_type)
                all_ones = IR.IntConst(lower_type(result_type), -1)
                return emit(IR.BinOp(new_value(lower_type(result_type), "not"), IR.BinOpKind.XOR, operand, all_ones))
            case "&":
                if isinstance(value, AST.Identifier):
                    symbol = lookup_ident(scopes, value.name)
                    if symbol and symbol.kind == AST.SymbolKind.FUNC:
                        return lower_identifier(value)
                return lower_lvalue(value)
            case "*":
                ptr = lower_rvalue(value)
                if isinstance(result_type, AST.ArrayType):
                    return decay_array(ptr, result_type)
                return emit(IR.Load(new_value(lower_type(result_type), "load"), ptr))
        raise ValueError("Unknown unary op")

    def lower_incdec(op: str, value: AST.Expr, is_postfix: bool) -> IR.Operand:
        ptr = lower_lvalue(value)
        expr_ctype = expr_type(value)
        current_val = emit(IR.Load(new_value(lower_type(expr_ctype), "load"), ptr))
        step = IR.IntConst(int_type(), 1)
        if isinstance(expr_ctype, AST.PointerType):
            index = step if op == "++" else IR.IntConst(int_type(), -1)
            new_val = emit(IR.Gep(new_value(lower_type(expr_ctype), "gep"), current_val, [index], lower_type(expr_ctype)))
        else:
            kind = IR.BinOpKind.ADD if op == "++" else IR.BinOpKind.SUB
            new_val = emit(IR.BinOp(new_value(lower_type(expr_ctype), "inc"), kind, current_val, step))
        emit(IR.Store(ptr, new_val))
        return current_val if is_postfix else new_val

    def lower_call(func_expr: AST.Expr, args: list[AST.Expr], result_type: AST.CType) -> IR.Operand:
        callee = lower_rvalue(func_expr)
        func_type = func_ctype(expr_type(func_expr))
        lowered_args: list[IR.Operand] = []
        for arg, param in zip(args, func_type.params, strict=False):
            lowered_args.append(coerce(lower_rvalue(arg), expr_type(arg), param.ctype))
        if func_type.variadic and len(args) > len(func_type.params):
            for arg in args[len(func_type.params):]:
                lowered_args.append(lower_rvalue(arg))
        if isinstance(result_type, AST.VoidType):
            emit(IR.Call(None, callee, lowered_args))
            return IR.ZeroInit(int_type())
        result = emit(IR.Call(new_value(lower_type(result_type), "call"), callee, lowered_args))
        return result

    def lower_conditional(cond: AST.Expr, then: AST.Expr, otherwise: AST.Expr, result_type: AST.CType) -> IR.Operand:
        then_block = new_block("cond.then")
        else_block = new_block("cond.else")
        end_block = new_block("cond.end")

        cond_val = to_bool(lower_rvalue(cond), expr_type(cond))
        set_term(IR.CondBr(cond_val, then_block, else_block))

        set_current(then_block)
        then_val = coerce(lower_rvalue(then), expr_type(then), result_type)
        set_term(IR.Br(end_block))

        set_current(else_block)
        else_val = coerce(lower_rvalue(otherwise), expr_type(otherwise), result_type)
        set_term(IR.Br(end_block))

        set_current(end_block)
        phi = IR.Phi(new_value(lower_type(result_type), "phi"), [(then_block, then_val), (else_block, else_val)])
        current_block().phis.append(phi)
        return phi.result

    def lower_member_ptr(value: AST.Expr, name: AST.Identifier, through_pointer: bool) -> IR.Operand:
        base_ptr = lower_rvalue(value) if through_pointer else lower_lvalue(value)
        struct_type = expr_type(value)
        if through_pointer:
            assert isinstance(struct_type, AST.PointerType)
            struct_type = struct_type.base
        assert isinstance(struct_type, (AST.StructType, AST.UnionType))
        if struct_type.fields is None:
            raise ValueError("Incomplete type")
        field_index = next((i for i, field in enumerate(struct_type.fields) if field.name and field.name.name == name.name), None)
        if field_index is None:
            raise ValueError("Unknown field")
        field = struct_type.fields[field_index]
        field_type = lower_type(field.ctype)
        result_type = IR.PointerType(field_type)
        if isinstance(struct_type, AST.UnionType):
            return emit(IR.Cast(new_value(result_type, "cast"), IR.CastKind.BITCAST, base_ptr, result_type))
        index = IR.IntConst(int_type(), field_index)
        return emit(IR.Gep(new_value(result_type, "gep"), base_ptr, [IR.IntConst(int_type(), 0), index], result_type))

    def lower_compound_literal(expr: AST.CompoundLiteral) -> IR.Operand:
        ctype = lower_type(expr.ctype)
        storage = emit(IR.Alloca(new_value(IR.PointerType(ctype), "tmp"), ctype))
        emit_initializer(storage, expr.ctype, expr.value)
        return storage

    def emit_initializer(ptr: IR.Operand, ctype: AST.CType, init: AST.Initializer) -> None:
        if isinstance(init, AST.InitList):
            match ctype:
                case AST.ArrayType(base=base, size=_):
                    emit_array_init(ptr, base, init)
                    return
                case AST.StructType(fields=fields) | AST.UnionType(fields=fields):
                    if fields is None:
                        raise ValueError("Initializer for incomplete type")
                    emit_struct_init(ptr, ctype, init)
                    return
            raise ValueError("Initializer list used for non-aggregate")
        value = coerce(lower_rvalue(init), expr_type(init), ctype)
        emit(IR.Store(ptr, value))

    def emit_array_init(ptr: IR.Operand, base: AST.CType, init: AST.InitList) -> None:
        index = 0
        for item in init.items:
            if item.designators:
                designator = item.designators[-1]
                if designator.index:
                    index_val = const_eval(designator.index)
                    if index_val is None:
                        raise ValueError("Non-constant array designator")
                    index = index_val
            elem_ptr = emit(IR.Gep(
                new_value(IR.PointerType(lower_type(base)), "gep"),
                ptr,
                [IR.IntConst(int_type(), 0), IR.IntConst(int_type(), index)],
                IR.PointerType(lower_type(base)),
            ))
            emit_initializer(elem_ptr, base, item.value)
            index += 1

    def emit_struct_init(ptr: IR.Operand, ctype: AST.StructType | AST.UnionType, init: AST.InitList) -> None:
        assert ctype.fields is not None
        field_iter = iter(ctype.fields)
        for item in init.items:
            field = designated_field(ctype, item.designators[-1]) if item.designators else next(field_iter, None)
            if field is None:
                raise ValueError("Too many initializers")
            field_ptr = field_ptr_for(ptr, ctype, field)
            emit_initializer(field_ptr, field.ctype, item.value)
            if isinstance(ctype, AST.UnionType):
                break

    def designated_field(ctype: AST.StructType | AST.UnionType, designator: AST.Designator) -> AST.Field:
        if designator.field is None:
            raise ValueError("Expected field designator")
        for field in ctype.fields or []:
            if field.name and field.name.name == designator.field.name:
                return field
        raise ValueError("Unknown designator field")

    def field_ptr_for(base_ptr: IR.Operand, ctype: AST.StructType | AST.UnionType, field: AST.Field) -> IR.Operand:
        assert ctype.fields is not None
        field_index = next(i for i, item in enumerate(ctype.fields) if item is field)
        field_type = IR.PointerType(lower_type(field.ctype))
        if isinstance(ctype, AST.UnionType):
            return emit(IR.Cast(new_value(field_type, "cast"), IR.CastKind.BITCAST, base_ptr, field_type))
        return emit(IR.Gep(
            new_value(field_type, "gep"),
            base_ptr,
            [IR.IntConst(int_type(), 0), IR.IntConst(int_type(), field_index)],
            field_type,
        ))

    def const_initializer(init: AST.Initializer, ctype: AST.CType) -> IR.Constant:
        if isinstance(init, AST.InitList):
            match ctype:
                case AST.ArrayType(base=base, size=_):
                    items = [const_initializer(item.value, base) for item in init.items]
                    return IR.AggregateConst(lower_type(ctype), items)
                case AST.StructType(fields=fields) | AST.UnionType(fields=fields):
                    if fields is None:
                        raise ValueError("Initializer for incomplete type")
                    items = [const_initializer(item.value, fields[idx].ctype) for idx, item in enumerate(init.items)]
                    return IR.AggregateConst(lower_type(ctype), items)
            raise ValueError("Initializer list used for non-aggregate")
        if isinstance(init, AST.IntLiteral):
            return IR.IntConst(lower_type(ctype), init.value)
        if isinstance(init, AST.BoolLiteral):
            return IR.BoolConst(lower_type(ctype), init.value)
        if isinstance(init, AST.FloatLiteral):
            return IR.FloatConst(lower_type(ctype), init.value)
        if isinstance(init, AST.CharLiteral):
            return IR.CharConst(lower_type(ctype), init.value)
        if isinstance(init, AST.StringLiteral):
            raise ValueError("String literal global initializer not supported")
        raise ValueError("Non-constant initializer")

    def decay_array(ptr: IR.Operand, ctype: AST.ArrayType) -> IR.Operand:
        elem_type = lower_type(ctype.base)
        result_type = IR.PointerType(elem_type)
        return emit(IR.Gep(
            new_value(result_type, "decay"),
            ptr,
            [IR.IntConst(int_type(), 0), IR.IntConst(int_type(), 0)],
            result_type,
        ))

    def string_global(value: str) -> IR.Global:
        nonlocal string_id
        if value in strings:
            return strings[value]
        char = char_type()
        elem_type = IR.ArrayType(char, len(value) + 1)
        global_type = IR.PointerType(elem_type)
        name = f".str.{string_id}"
        string_id += 1
        global_var = IR.Global(name, global_type, elem_type, IR.StringConst(elem_type, value), True, None)
        module.globals.append(global_var)
        strings[value] = global_var
        return global_var

    def string_ptr(value: str) -> IR.Operand:
        global_var = string_global(value)
        return emit(IR.Gep(
            new_value(IR.PointerType(char_type()), "str"),
            global_var,
            [IR.IntConst(int_type(), 0), IR.IntConst(int_type(), 0)],
            IR.PointerType(char_type()),
        ))

    def to_bool(value: IR.Operand, ctype: AST.CType) -> IR.Operand:
        if isinstance(ctype, AST.PointerType):
            return emit(IR.ICmp(new_value(bool_type(), "ptrbool"), IR.CmpKind.NE, value, IR.NullPtr(lower_type(ctype)), False))
        if is_float(ctype):
            zero = IR.FloatConst(lower_type(ctype), 0.0)
            return emit(IR.FCmp(new_value(bool_type(), "fbool"), IR.CmpKind.NE, value, zero))
        zero = IR.IntConst(int_type(), 0)
        return emit(IR.ICmp(new_value(bool_type(), "ibool"), IR.CmpKind.NE, value, zero, is_signed(ctype)))

    def coerce(value: IR.Operand, from_type: AST.CType, to_type: AST.CType) -> IR.Operand:
        if type_equal(from_type, to_type):
            return value
        from_ir = lower_type(from_type)
        to_ir = lower_type(to_type)
        kind = cast_kind(from_ir, to_ir)
        return emit(IR.Cast(new_value(to_ir, "cast"), kind, value, to_ir))

    def cast_kind(from_type: IR.Type, to_type: IR.Type) -> IR.CastKind:
        if isinstance(from_type, IR.PointerType) or isinstance(to_type, IR.PointerType):
            return IR.CastKind.PTR if isinstance(from_type, IR.IntType) or isinstance(to_type, IR.IntType) else IR.CastKind.BITCAST
        if isinstance(from_type, IR.FloatType) or isinstance(to_type, IR.FloatType):
            return IR.CastKind.FLOAT
        return IR.CastKind.INT

    def lower_type(ctype: AST.CType) -> IR.Type:
        match ctype:
            case AST.BuiltinType(keywords=keywords):
                names = [kw.name for kw in keywords]
                if "bool" in names:
                    return bool_type()
                if "float" in names:
                    return IR.FloatType("float")
                if "double" in names:
                    return IR.FloatType("double")
                return IR.IntType(int_bits(names), "unsigned" not in names)
            case AST.VoidType():
                return IR.VoidType()
            case AST.PointerType(base=base):
                return IR.PointerType(lower_type(base))
            case AST.ArrayType(base=base, size=size):
                count = size.value if isinstance(size, AST.IntLiteral) else None
                return IR.ArrayType(lower_type(base), count)
            case AST.FunctionType(return_type=return_type, params=params, variadic=variadic):
                return IR.FunctionType(lower_type(return_type), [param_type(param.ctype) for param in params], variadic)
            case AST.StructType(name=name, fields=fields):
                if fields is None:
                    return IR.StructType(name.name if name else None, None)
                ir_fields = [IR.FieldType(field.name.name if field.name else None, lower_type(field.ctype)) for field in fields]
                return IR.StructType(name.name if name else None, ir_fields)
            case AST.UnionType(name=name, fields=fields):
                if fields is None:
                    return IR.UnionType(name.name if name else None, None)
                ir_fields = [IR.FieldType(field.name.name if field.name else None, lower_type(field.ctype)) for field in fields]
                return IR.UnionType(name.name if name else None, ir_fields)
            case AST.EnumType():
                return int_type()
            case AST.NamedType():
                return int_type()
        raise ValueError("Unknown type")

    def param_type(ctype: AST.CType) -> IR.Type:
        match ctype:
            case AST.ArrayType(base=base):
                return IR.PointerType(lower_type(base))
            case AST.FunctionType():
                return IR.PointerType(lower_type(ctype))
        return lower_type(ctype)

    def func_ctype(ctype: AST.CType) -> AST.FunctionType:
        match ctype:
            case AST.FunctionType():
                return ctype
            case AST.PointerType(base=base) if isinstance(base, AST.FunctionType):
                return base
        raise ValueError("Expected function type")

    def int_bits(names: list[str]) -> int:
        long_count = sum(1 for name in names if name == "long")
        if "char" in names:
            return 8
        if "short" in names:
            return 16
        if long_count >= 1:
            return 64
        return 32

    def type_equal(left: AST.CType, right: AST.CType) -> bool:
        return type_key(left) == type_key(right)

    def type_key(ctype: AST.CType) -> tuple:
        match ctype:
            case AST.BuiltinType(keywords=keywords):
                return ("builtin", tuple(sorted(kw.name for kw in keywords)))
            case AST.VoidType():
                return ("void",)
            case AST.PointerType(base=base):
                return ("ptr", type_key(base))
            case AST.ArrayType(base=base, size=size):
                size_val = size.value if isinstance(size, AST.IntLiteral) else None
                return ("array", type_key(base), size_val)
            case AST.FunctionType(return_type=return_type, params=params, variadic=variadic):
                return ("func", type_key(return_type), tuple(type_key(p.ctype) for p in params), variadic)
            case AST.StructType(name=name):
                return ("struct", name.name if name else id(ctype))
            case AST.UnionType(name=name):
                return ("union", name.name if name else id(ctype))
            case AST.EnumType(name=name):
                return ("enum", name.name if name else id(ctype))
            case AST.NamedType(name=name):
                return ("named", name.name)
        return ("unknown",)

    def sizeof(ctype: AST.CType) -> int:
        match ctype:
            case AST.BuiltinType(keywords=keywords):
                names = {kw.name for kw in keywords}
                if "bool" in names:
                    return 1
                if "char" in names:
                    return 1
                if "short" in names:
                    return 2
                if "long" in names:
                    return 8
                if "float" in names:
                    return 4
                if "double" in names:
                    return 8
                return 4
            case AST.EnumType():
                return 4
            case AST.PointerType():
                return 8
            case AST.ArrayType(base=base, size=size):
                count = size.value if isinstance(size, AST.IntLiteral) else 0
                return sizeof(base) * count
            case AST.StructType(fields=fields):
                return sum(sizeof(field.ctype) for field in (fields or []))
            case AST.UnionType(fields=fields):
                return max((sizeof(field.ctype) for field in (fields or [])), default=0)
        return 0

    def is_float(ctype: AST.CType) -> bool:
        return isinstance(ctype, AST.BuiltinType) and any(kw.name in {"float", "double"} for kw in ctype.keywords)

    def is_integer(ctype: AST.CType) -> bool:
        return isinstance(ctype, AST.BuiltinType) and any(kw.name in {"bool", "char", "short", "int", "long", "signed", "unsigned"} for kw in ctype.keywords)

    def is_signed(ctype: AST.CType) -> bool:
        if isinstance(ctype, AST.BuiltinType):
            return all(kw.name != "unsigned" for kw in ctype.keywords)
        return True

    def float_result_type(left: AST.CType, right: AST.CType) -> AST.CType:
        if isinstance(left, AST.BuiltinType) and any(kw.name == "double" for kw in left.keywords):
            return left
        if isinstance(right, AST.BuiltinType) and any(kw.name == "double" for kw in right.keywords):
            return right
        return AST.BuiltinType([AST.TypeKeyword("float")])

    def bool_type() -> IR.IntType:
        return IR.IntType(1, False)

    def int_type() -> IR.IntType:
        return IR.IntType(32, True)

    def int_type_ast() -> AST.CType:
        return AST.BuiltinType([AST.TypeKeyword("int")])

    def char_type() -> IR.IntType:
        return IR.IntType(8, True)

    def zero_const(ctype: AST.CType) -> IR.Operand:
        ir_type = lower_type(ctype)
        if isinstance(ir_type, IR.FloatType):
            return IR.FloatConst(ir_type, 0.0)
        if isinstance(ir_type, IR.PointerType):
            return IR.NullPtr(ir_type)
        return IR.IntConst(ir_type, 0)

    def cmp_kind(op: str) -> IR.CmpKind:
        return {
            "==": IR.CmpKind.EQ,
            "!=": IR.CmpKind.NE,
            "<": IR.CmpKind.LT,
            "<=": IR.CmpKind.LE,
            ">": IR.CmpKind.GT,
            ">=": IR.CmpKind.GE,
        }[op]

    def binop_kind(op: str) -> IR.BinOpKind:
        return {
            "+": IR.BinOpKind.ADD,
            "-": IR.BinOpKind.SUB,
            "*": IR.BinOpKind.MUL,
            "/": IR.BinOpKind.DIV,
            "%": IR.BinOpKind.REM,
            "&": IR.BinOpKind.AND,
            "|": IR.BinOpKind.OR,
            "^": IR.BinOpKind.XOR,
            "<<": IR.BinOpKind.SHL,
            ">>": IR.BinOpKind.SHR,
        }[op]

    def expr_type(expr: AST.Expr) -> AST.CType:
        assert expr.expr_type is not None
        return expr.expr_type

    def current_block() -> IR.BasicBlock:
        assert current is not None
        return current

    def new_value(ctype: IR.Type, hint: str) -> IR.Value:
        nonlocal value_id
        name = f"{hint}.{value_id}"
        value_id += 1
        return IR.Value(name, ctype)

    def new_block(hint: str) -> IR.BasicBlock:
        nonlocal block_id, current
        name = f"{hint}.{block_id}"
        block_id += 1
        block = IR.BasicBlock(name)
        blocks.append(block)
        if current is None:
            current = block
        return block

    def set_current(block: IR.BasicBlock) -> None:
        nonlocal current
        current = block

    def set_term(term: IR.Terminator) -> None:
        if current is None or current.term is not None:
            return
        current.term = term

    def emit(instr: IR.Instr) -> IR.Operand:
        assert current is not None
        current.instrs.append(instr)
        if isinstance(instr, IR.Call):
            return instr.result if instr.result is not None else IR.ZeroInit(int_type())
        if isinstance(instr, (IR.BinOp, IR.ICmp, IR.FCmp, IR.Cast, IR.Select, IR.Alloca, IR.Load, IR.Gep)):
            return instr.result
        return IR.ZeroInit(int_type())

    def push_scope() -> None:
        local_vars.append({})

    def pop_scope() -> None:
        local_vars.pop()

    def bind_local(name: str, storage: IR.Operand) -> None:
        local_vars[-1][name] = storage

    def label_block(name: str) -> IR.BasicBlock:
        if name not in labels:
            labels[name] = new_block(f"label.{name}")
        return labels[name]

    collect_globals(program)
    for item in program.items:
        if isinstance(item, AST.FunctionDef):
            module.functions.append(lower_function(item))
    return module
