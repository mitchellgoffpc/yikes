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
    return _Lowerer().lower(program)


class _Lowerer:
    def __init__(self) -> None:
        self.module = IR.Module([], [])
        self.value_id = 0
        self.block_id = 0
        self.string_id = 0
        self.blocks: list[IR.BasicBlock] = []
        self.current: IR.BasicBlock | None = None
        self.func: AST.FunctionDef | None = None
        self.scopes: list[AST.Scope] = []
        self.locals: list[dict[str, IR.Operand]] = []
        self.globals: dict[str, IR.Global] = {}
        self.functions: dict[str, IR.Value] = {}
        self.labels: dict[str, IR.BasicBlock] = {}
        self.loop_stack: list[LoopContext] = []
        self.switch_stack: list[IR.BasicBlock] = []
        self.strings: dict[str, IR.Global] = {}

    def lower(self, program: AST.Program) -> IR.Module:
        self._collect_globals(program)
        for item in program.items:
            if isinstance(item, AST.FunctionDef):
                self.module.functions.append(self._lower_function(item))
        return self.module

    def _collect_globals(self, program: AST.Program) -> None:
        for item in program.items:
            match item:
                case AST.FunctionDef():
                    func_type = self._lower_type(item.ctype)
                    func_ptr_type = IR.PointerType(func_type)
                    self.functions[item.name.name] = IR.Value(item.name.name, func_ptr_type)
                case AST.VarDecl():
                    self._add_global(item)

    def _add_global(self, decl: AST.VarDecl) -> None:
        elem_type = self._lower_type(decl.ctype)
        global_type = IR.PointerType(elem_type)
        init = self._const_initializer(decl.init, decl.ctype) if decl.init else IR.ZeroInit(elem_type)
        global_var = IR.Global(decl.name.name, global_type, elem_type, init, False, None)
        self.globals[decl.name.name] = global_var
        self.module.globals.append(global_var)

    def _lower_function(self, func: AST.FunctionDef) -> IR.Function:
        self.func = func
        self.blocks = []
        self.current = None
        self.labels = {}
        self.loop_stack = []
        self.switch_stack = []
        self.scopes = [func.scope, func.body.scope]
        self.locals = []

        func_type = cast(IR.FunctionType, self._lower_type(func.ctype))
        params = [IR.Param(param.name.name if param.name else f"param{idx}", self._param_type(param.ctype)) for idx, param in enumerate(func.ctype.params)]

        entry = self._new_block("entry")
        self._set_current(entry)
        self._push_scope()

        for param, param_ast in zip(params, func.ctype.params, strict=False):
            if param_ast.name is None:
                continue
            storage = self._emit(IR.Alloca(self._new_value(IR.PointerType(param.type), f"{param.name}.addr"), param.type))
            self._emit(IR.Store(storage, param))
            self._bind_local(param_ast.name.name, storage)

        self._lower_block(func.body)
        if self.current and self.current.term is None:
            if isinstance(func.ctype.return_type, AST.VoidType):
                self._set_term(IR.Ret(None))
            else:
                zero = self._zero_const(func.ctype.return_type)
                self._set_term(IR.Ret(zero))

        self._pop_scope()
        return IR.Function(func.name.name, func_type, params, self.blocks)

    def _lower_block(self, block: AST.Block) -> None:
        self.scopes.append(block.scope)
        self._push_scope()
        for item in block.items:
            self._lower_stmt(item)
        self._pop_scope()
        self.scopes.pop()

    def _lower_stmt(self, stmt: AST.Stmt) -> None:
        if self.current is None:
            return
        match stmt:
            case AST.Block():
                self._lower_block(stmt)
            case AST.VarDecl():
                self._lower_var_decl(stmt)
            case AST.TypeDef() | AST.StructDef() | AST.UnionDef() | AST.EnumDef():
                return
            case AST.ExprStmt(expr=expr):
                if expr:
                    self._lower_rvalue(expr)
            case AST.Return(value=value):
                if value is None:
                    self._set_term(IR.Ret(None))
                else:
                    assert self.func is not None
                    ret_value = self._coerce(self._lower_rvalue(value), self._expr_type(value), self.func.ctype.return_type)
                    self._set_term(IR.Ret(ret_value))
            case AST.If(cond=cond, then=then, otherwise=otherwise):
                self._lower_if(cond, then, otherwise)
            case AST.While(cond=cond, body=body):
                self._lower_while(cond, body)
            case AST.Break():
                if not self.loop_stack and not self.switch_stack:
                    return
                target = self.switch_stack[-1] if self.switch_stack else self.loop_stack[-1].break_target
                self._set_term(IR.Br(target))
            case AST.Continue():
                if not self.loop_stack:
                    return
                self._set_term(IR.Br(self.loop_stack[-1].continue_target))
            case AST.Switch(expr=expr, body=body):
                self._lower_switch(expr, body)
            case AST.Case() | AST.Default():
                return
            case AST.Label(name=name, stmt=inner):
                target = self._label_block(name.name)
                if self.current.term is None:
                    self._set_term(IR.Br(target))
                self._set_current(target)
                self._lower_stmt(inner)
            case AST.Goto(target=target):
                self._set_term(IR.Br(self._label_block(target.name)))

    def _lower_if(self, cond: AST.Expr, then: AST.Block, otherwise: AST.Block | None) -> None:
        then_block = self._new_block("if.then")
        end_block = self._new_block("if.end")
        else_block = self._new_block("if.else") if otherwise else end_block

        cond_val = self._to_bool(self._lower_rvalue(cond), self._expr_type(cond))
        self._set_term(IR.CondBr(cond_val, then_block, else_block))

        self._set_current(then_block)
        self._lower_block(then)
        if self._current().term is None:
            self._set_term(IR.Br(end_block))

        if otherwise:
            self._set_current(else_block)
            self._lower_block(otherwise)
            if self._current().term is None:
                self._set_term(IR.Br(end_block))

        self._set_current(end_block)

    def _lower_while(self, cond: AST.Expr, body: AST.Block) -> None:
        cond_block = self._new_block("while.cond")
        body_block = self._new_block("while.body")
        end_block = self._new_block("while.end")

        self._set_term(IR.Br(cond_block))

        self._set_current(cond_block)
        cond_val = self._to_bool(self._lower_rvalue(cond), self._expr_type(cond))
        self._set_term(IR.CondBr(cond_val, body_block, end_block))

        self._set_current(body_block)
        self.loop_stack.append(LoopContext(cond_block, end_block))
        self._lower_block(body)
        self.loop_stack.pop()
        if self._current().term is None:
            self._set_term(IR.Br(cond_block))

        self._set_current(end_block)

    def _lower_switch(self, expr: AST.Expr, body: AST.Block) -> None:
        end_block = self._new_block("switch.end")
        default_block = None
        case_blocks: list[tuple[int, IR.BasicBlock]] = []
        ordered_labels: list[tuple[AST.Case | AST.Default, IR.BasicBlock]] = []

        self.switch_stack.append(end_block)

        for item in body.items:
            match item:
                case AST.Case(value=value):
                    const = const_eval(value)
                    if const is None:
                        continue
                    block = self._new_block("switch.case")
                    case_blocks.append((const, block))
                    ordered_labels.append((item, block))
                case AST.Default():
                    default_block = self._new_block("switch.default")
                    ordered_labels.append((item, default_block))

        if default_block is None:
            default_block = end_block

        switch_value = self._coerce(self._lower_rvalue(expr), self._expr_type(expr), self._int_type_ast())
        cases = [IR.SwitchCase(IR.IntConst(self._int_type(), value), block) for value, block in case_blocks]
        self._set_term(IR.Switch(switch_value, default_block, cases))

        ordered_blocks = [block for _, block in ordered_labels]
        for index, (item, target) in enumerate(ordered_labels):
            self._set_current(target)
            self._lower_block(item.body)
            if self._current().term is None:
                fallthrough = ordered_blocks[index + 1] if index + 1 < len(ordered_blocks) else end_block
                self._set_term(IR.Br(fallthrough))

        self.switch_stack.pop()
        self._set_current(end_block)

    def _lower_var_decl(self, decl: AST.VarDecl) -> None:
        var_type = self._lower_type(decl.ctype)
        storage = self._emit(IR.Alloca(self._new_value(IR.PointerType(var_type), f"{decl.name.name}.addr"), var_type))
        self._bind_local(decl.name.name, storage)
        if decl.init:
            self._emit_initializer(storage, decl.ctype, decl.init)

    def _lower_rvalue(self, expr: AST.Expr) -> IR.Operand:
        match expr:
            case AST.IntLiteral(value=value):
                return IR.IntConst(self._lower_type(self._expr_type(expr)), value)
            case AST.BoolLiteral(value=value):
                return IR.BoolConst(self._lower_type(self._expr_type(expr)), value)
            case AST.FloatLiteral(value=value):
                return IR.FloatConst(self._lower_type(self._expr_type(expr)), value)
            case AST.CharLiteral(value=value):
                return IR.CharConst(self._lower_type(self._expr_type(expr)), value)
            case AST.StringLiteral(value=value):
                return self._string_ptr(value)
            case AST.Identifier():
                return self._lower_identifier(expr)
            case AST.Assign(target=target, value=value):
                return self._lower_assign(target, value)
            case AST.Binary(op=op, left=left, right=right):
                return self._lower_binary(op, left, right, self._expr_type(expr))
            case AST.Unary(op=op, value=value):
                return self._lower_unary(op, value, self._expr_type(expr))
            case AST.IncDec(op=op, value=value, is_postfix=is_postfix):
                return self._lower_incdec(op, value, is_postfix)
            case AST.Call(func=func, args=args):
                return self._lower_call(func, args, self._expr_type(expr))
            case AST.Member():
                return self._load_lvalue(expr)
            case AST.Conditional(cond=cond, then=then, otherwise=otherwise):
                return self._lower_conditional(cond, then, otherwise, self._expr_type(expr))
            case AST.Cast(target_type=target_type, value=value):
                return self._coerce(self._lower_rvalue(value), self._expr_type(value), target_type)
            case AST.Sizeof(value=value):
                target = value if isinstance(value, AST.CType) else self._expr_type(value)
                return IR.IntConst(self._int_type(), self._sizeof(target))
            case AST.CompoundLiteral():
                return self._load_lvalue(expr)
        raise ValueError("Unknown expression")

    def _load_lvalue(self, expr: AST.Expr) -> IR.Operand:
        ptr = self._lower_lvalue(expr)
        expr_type = self._expr_type(expr)
        if isinstance(expr_type, AST.ArrayType):
            return self._decay_array(ptr, expr_type)
        return self._emit(IR.Load(self._new_value(self._lower_type(expr_type), "load"), ptr))

    def _lower_lvalue(self, expr: AST.Expr) -> IR.Operand:
        match expr:
            case AST.Identifier():
                return self._lower_ident_lvalue(expr)
            case AST.Unary(op="*", value=value):
                return self._lower_rvalue(value)
            case AST.Member(value=value, name=name, through_pointer=through_pointer):
                return self._lower_member_ptr(value, name, through_pointer)
            case AST.StringLiteral(value=value):
                return self._string_global(value)
            case AST.CompoundLiteral():
                return self._lower_compound_literal(expr)
        raise ValueError("Expression is not an lvalue")

    def _lower_identifier(self, expr: AST.Identifier) -> IR.Operand:
        symbol = lookup_ident(self.scopes, expr.name)
        if symbol and symbol.kind == AST.SymbolKind.ENUM_CONST and isinstance(symbol.decl, AST.Enumerator):
            value = const_eval(symbol.decl.value) if symbol.decl.value else 0
            if value is None:
                value = 0
            return IR.IntConst(self._int_type(), value)
        if symbol and symbol.kind == AST.SymbolKind.FUNC:
            func = self.functions.get(expr.name)
            if func is None:
                assert symbol.ctype is not None
                func_type = self._lower_type(symbol.ctype)
                func = IR.Value(expr.name, IR.PointerType(func_type))
                self.functions[expr.name] = func
            return func
        return self._load_lvalue(expr)

    def _lower_ident_lvalue(self, expr: AST.Identifier) -> IR.Operand:
        for scope in reversed(self.locals):
            if expr.name in scope:
                return scope[expr.name]
        if expr.name in self.globals:
            return self.globals[expr.name]
        raise ValueError(f"Unknown identifier '{expr.name}'")

    def _lower_assign(self, target: AST.Expr, value: AST.Expr) -> IR.Operand:
        target_ptr = self._lower_lvalue(target)
        stored = self._coerce(self._lower_rvalue(value), self._expr_type(value), self._expr_type(target))
        self._emit(IR.Store(target_ptr, stored))
        return stored

    def _lower_binary(self, op: str, left: AST.Expr, right: AST.Expr, result_type: AST.CType) -> IR.Operand:
        if op == ",":
            self._lower_rvalue(left)
            return self._lower_rvalue(right)
        if op in {"&&", "||"}:
            return self._lower_logical(op, left, right)
        if op in {"==", "!=", "<", "<=", ">", ">="}:
            return self._lower_cmp(op, left, right)
        left_val = self._lower_rvalue(left)
        right_val = self._lower_rvalue(right)
        if op in {"+", "-"} and (isinstance(self._expr_type(left), AST.PointerType) or isinstance(self._expr_type(right), AST.PointerType)):
            return self._lower_pointer_arith(op, left, right, left_val, right_val)
        left_val = self._coerce(left_val, self._expr_type(left), result_type)
        right_val = self._coerce(right_val, self._expr_type(right), result_type)
        binop = self._binop_kind(op)
        return self._emit(IR.BinOp(self._new_value(self._lower_type(result_type), "binop"), binop, left_val, right_val))

    def _lower_cmp(self, op: str, left: AST.Expr, right: AST.Expr) -> IR.Operand:
        left_val = self._lower_rvalue(left)
        right_val = self._lower_rvalue(right)
        if self._is_float(self._expr_type(left)) or self._is_float(self._expr_type(right)):
            target = self._float_result_type(self._expr_type(left), self._expr_type(right))
            left_val = self._coerce(left_val, self._expr_type(left), target)
            right_val = self._coerce(right_val, self._expr_type(right), target)
            return self._emit(IR.FCmp(self._new_value(self._bool_type(), "fcmp"), self._cmp_kind(op), left_val, right_val))
        if isinstance(self._expr_type(left), AST.PointerType) and isinstance(self._expr_type(right), AST.PointerType):
            return self._emit(IR.ICmp(self._new_value(self._bool_type(), "icmp"), self._cmp_kind(op), left_val, right_val, False))
        left_val = self._coerce(left_val, self._expr_type(left), self._int_type_ast())
        right_val = self._coerce(right_val, self._expr_type(right), self._int_type_ast())
        signed = self._is_signed(self._expr_type(left)) and self._is_signed(self._expr_type(right))
        return self._emit(IR.ICmp(self._new_value(self._bool_type(), "icmp"), self._cmp_kind(op), left_val, right_val, signed))

    def _lower_logical(self, op: str, left: AST.Expr, right: AST.Expr) -> IR.Operand:
        left_block = self._current()
        right_block = self._new_block("logic.rhs")
        end_block = self._new_block("logic.end")

        left_val = self._to_bool(self._lower_rvalue(left), self._expr_type(left))
        if op == "&&":
            self._set_term(IR.CondBr(left_val, right_block, end_block))
        else:
            self._set_term(IR.CondBr(left_val, end_block, right_block))

        self._set_current(right_block)
        right_val = self._to_bool(self._lower_rvalue(right), self._expr_type(right))
        self._set_term(IR.Br(end_block))

        self._set_current(end_block)
        phi = IR.Phi(self._new_value(self._bool_type(), "phi"), [(left_block, IR.BoolConst(self._bool_type(), op == "||")), (right_block, right_val)])
        self._current().phis.append(phi)
        return phi.result

    def _lower_pointer_arith(self, op: str, left: AST.Expr, right: AST.Expr, left_val: IR.Operand, right_val: IR.Operand) -> IR.Operand:
        if isinstance(self._expr_type(left), AST.PointerType) and self._is_integer(self._expr_type(right)):
            index = self._coerce(right_val, self._expr_type(right), self._int_type_ast())
            if op == "-":
                index = self._emit(IR.BinOp(self._new_value(self._int_type(), "neg"), IR.BinOpKind.SUB, IR.IntConst(self._int_type(), 0), index))
            result_type = self._lower_type(self._expr_type(left))
            return self._emit(IR.Gep(self._new_value(result_type, "gep"), left_val, [index], result_type))
        if isinstance(self._expr_type(right), AST.PointerType) and self._is_integer(self._expr_type(left)) and op == "+":
            index = self._coerce(left_val, self._expr_type(left), self._int_type_ast())
            result_type = self._lower_type(self._expr_type(right))
            return self._emit(IR.Gep(self._new_value(result_type, "gep"), right_val, [index], result_type))
        raise ValueError("Unsupported pointer arithmetic")

    def _lower_unary(self, op: str, value: AST.Expr, result_type: AST.CType) -> IR.Operand:
        match op:
            case "+":
                return self._coerce(self._lower_rvalue(value), self._expr_type(value), result_type)
            case "-":
                operand = self._coerce(self._lower_rvalue(value), self._expr_type(value), result_type)
                zero = self._zero_const(result_type)
                return self._emit(IR.BinOp(self._new_value(self._lower_type(result_type), "neg"), IR.BinOpKind.SUB, zero, operand))
            case "!":
                bool_val = self._to_bool(self._lower_rvalue(value), self._expr_type(value))
                return self._emit(IR.ICmp(self._new_value(self._bool_type(), "not"), IR.CmpKind.EQ, bool_val, IR.BoolConst(self._bool_type(), False), False))
            case "~":
                operand = self._coerce(self._lower_rvalue(value), self._expr_type(value), result_type)
                all_ones = IR.IntConst(self._lower_type(result_type), -1)
                return self._emit(IR.BinOp(self._new_value(self._lower_type(result_type), "not"), IR.BinOpKind.XOR, operand, all_ones))
            case "&":
                if isinstance(value, AST.Identifier):
                    symbol = lookup_ident(self.scopes, value.name)
                    if symbol and symbol.kind == AST.SymbolKind.FUNC:
                        return self._lower_identifier(value)
                return self._lower_lvalue(value)
            case "*":
                ptr = self._lower_rvalue(value)
                if isinstance(result_type, AST.ArrayType):
                    return self._decay_array(ptr, result_type)
                return self._emit(IR.Load(self._new_value(self._lower_type(result_type), "load"), ptr))
        raise ValueError("Unknown unary op")

    def _lower_incdec(self, op: str, value: AST.Expr, is_postfix: bool) -> IR.Operand:
        ptr = self._lower_lvalue(value)
        expr_type = self._expr_type(value)
        current = self._emit(IR.Load(self._new_value(self._lower_type(expr_type), "load"), ptr))
        step = IR.IntConst(self._int_type(), 1)
        if isinstance(expr_type, AST.PointerType):
            index = step if op == "++" else IR.IntConst(self._int_type(), -1)
            new_val = self._emit(IR.Gep(self._new_value(self._lower_type(expr_type), "gep"), current, [index], self._lower_type(expr_type)))
        else:
            kind = IR.BinOpKind.ADD if op == "++" else IR.BinOpKind.SUB
            new_val = self._emit(IR.BinOp(self._new_value(self._lower_type(expr_type), "inc"), kind, current, step))
        self._emit(IR.Store(ptr, new_val))
        return current if is_postfix else new_val

    def _lower_call(self, func: AST.Expr, args: list[AST.Expr], result_type: AST.CType) -> IR.Operand:
        callee = self._lower_rvalue(func)
        func_type = self._func_ctype(self._expr_type(func))
        lowered_args: list[IR.Operand] = []
        for arg, param in zip(args, func_type.params, strict=False):
            lowered_args.append(self._coerce(self._lower_rvalue(arg), self._expr_type(arg), param.ctype))
        if func_type.variadic and len(args) > len(func_type.params):
            for arg in args[len(func_type.params):]:
                lowered_args.append(self._lower_rvalue(arg))
        if isinstance(result_type, AST.VoidType):
            self._emit(IR.Call(None, callee, lowered_args))
            return IR.ZeroInit(self._int_type())
        result = self._emit(IR.Call(self._new_value(self._lower_type(result_type), "call"), callee, lowered_args))
        return result

    def _lower_conditional(self, cond: AST.Expr, then: AST.Expr, otherwise: AST.Expr, result_type: AST.CType) -> IR.Operand:
        then_block = self._new_block("cond.then")
        else_block = self._new_block("cond.else")
        end_block = self._new_block("cond.end")

        cond_val = self._to_bool(self._lower_rvalue(cond), self._expr_type(cond))
        self._set_term(IR.CondBr(cond_val, then_block, else_block))

        self._set_current(then_block)
        then_val = self._coerce(self._lower_rvalue(then), self._expr_type(then), result_type)
        self._set_term(IR.Br(end_block))

        self._set_current(else_block)
        else_val = self._coerce(self._lower_rvalue(otherwise), self._expr_type(otherwise), result_type)
        self._set_term(IR.Br(end_block))

        self._set_current(end_block)
        phi = IR.Phi(self._new_value(self._lower_type(result_type), "phi"), [(then_block, then_val), (else_block, else_val)])
        self._current().phis.append(phi)
        return phi.result

    def _lower_member_ptr(self, value: AST.Expr, name: AST.Identifier, through_pointer: bool) -> IR.Operand:
        base_ptr = self._lower_rvalue(value) if through_pointer else self._lower_lvalue(value)
        struct_type = self._expr_type(value)
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
        field_type = self._lower_type(field.ctype)
        result_type = IR.PointerType(field_type)
        if isinstance(struct_type, AST.UnionType):
            return self._emit(IR.Cast(self._new_value(result_type, "cast"), IR.CastKind.BITCAST, base_ptr, result_type))
        index = IR.IntConst(self._int_type(), field_index)
        return self._emit(IR.Gep(self._new_value(result_type, "gep"), base_ptr, [IR.IntConst(self._int_type(), 0), index], result_type))

    def _lower_compound_literal(self, expr: AST.CompoundLiteral) -> IR.Operand:
        ctype = self._lower_type(expr.ctype)
        storage = self._emit(IR.Alloca(self._new_value(IR.PointerType(ctype), "tmp"), ctype))
        self._emit_initializer(storage, expr.ctype, expr.value)
        return storage

    def _emit_initializer(self, ptr: IR.Operand, ctype: AST.CType, init: AST.Initializer) -> None:
        if isinstance(init, AST.InitList):
            match ctype:
                case AST.ArrayType(base=base, size=_):
                    self._emit_array_init(ptr, base, init)
                    return
                case AST.StructType(fields=fields) | AST.UnionType(fields=fields):
                    if fields is None:
                        raise ValueError("Initializer for incomplete type")
                    self._emit_struct_init(ptr, ctype, init)
                    return
            raise ValueError("Initializer list used for non-aggregate")
        value = self._coerce(self._lower_rvalue(init), self._expr_type(init), ctype)
        self._emit(IR.Store(ptr, value))

    def _emit_array_init(self, ptr: IR.Operand, base: AST.CType, init: AST.InitList) -> None:
        index = 0
        for item in init.items:
            if item.designators:
                designator = item.designators[-1]
                if designator.index:
                    index_val = const_eval(designator.index)
                    if index_val is None:
                        raise ValueError("Non-constant array designator")
                    index = index_val
            elem_ptr = self._emit(IR.Gep(
                self._new_value(IR.PointerType(self._lower_type(base)), "gep"),
                ptr,
                [IR.IntConst(self._int_type(), 0), IR.IntConst(self._int_type(), index)],
                IR.PointerType(self._lower_type(base)),
            ))
            self._emit_initializer(elem_ptr, base, item.value)
            index += 1

    def _emit_struct_init(self, ptr: IR.Operand, ctype: AST.StructType | AST.UnionType, init: AST.InitList) -> None:
        assert ctype.fields is not None
        field_iter = iter(ctype.fields)
        for item in init.items:
            field = self._designated_field(ctype, item.designators[-1]) if item.designators else next(field_iter, None)
            if field is None:
                raise ValueError("Too many initializers")
            field_ptr = self._field_ptr(ptr, ctype, field)
            self._emit_initializer(field_ptr, field.ctype, item.value)
            if isinstance(ctype, AST.UnionType):
                break

    def _designated_field(self, ctype: AST.StructType | AST.UnionType, designator: AST.Designator) -> AST.Field:
        if designator.field is None:
            raise ValueError("Expected field designator")
        for field in ctype.fields or []:
            if field.name and field.name.name == designator.field.name:
                return field
        raise ValueError("Unknown designator field")

    def _field_ptr(self, base_ptr: IR.Operand, ctype: AST.StructType | AST.UnionType, field: AST.Field) -> IR.Operand:
        assert ctype.fields is not None
        field_index = next(i for i, item in enumerate(ctype.fields) if item is field)
        field_type = IR.PointerType(self._lower_type(field.ctype))
        if isinstance(ctype, AST.UnionType):
            return self._emit(IR.Cast(self._new_value(field_type, "cast"), IR.CastKind.BITCAST, base_ptr, field_type))
        return self._emit(IR.Gep(
            self._new_value(field_type, "gep"),
            base_ptr,
            [IR.IntConst(self._int_type(), 0), IR.IntConst(self._int_type(), field_index)],
            field_type,
        ))

    def _const_initializer(self, init: AST.Initializer, ctype: AST.CType) -> IR.Constant:
        if isinstance(init, AST.InitList):
            match ctype:
                case AST.ArrayType(base=base, size=_):
                    items = [self._const_initializer(item.value, base) for item in init.items]
                    return IR.AggregateConst(self._lower_type(ctype), items)
                case AST.StructType(fields=fields) | AST.UnionType(fields=fields):
                    if fields is None:
                        raise ValueError("Initializer for incomplete type")
                    items = [self._const_initializer(item.value, fields[idx].ctype) for idx, item in enumerate(init.items)]
                    return IR.AggregateConst(self._lower_type(ctype), items)
            raise ValueError("Initializer list used for non-aggregate")
        if isinstance(init, AST.IntLiteral):
            return IR.IntConst(self._lower_type(ctype), init.value)
        if isinstance(init, AST.BoolLiteral):
            return IR.BoolConst(self._lower_type(ctype), init.value)
        if isinstance(init, AST.FloatLiteral):
            return IR.FloatConst(self._lower_type(ctype), init.value)
        if isinstance(init, AST.CharLiteral):
            return IR.CharConst(self._lower_type(ctype), init.value)
        if isinstance(init, AST.StringLiteral):
            raise ValueError("String literal global initializer not supported")
        raise ValueError("Non-constant initializer")

    def _decay_array(self, ptr: IR.Operand, ctype: AST.ArrayType) -> IR.Operand:
        elem_type = self._lower_type(ctype.base)
        result_type = IR.PointerType(elem_type)
        return self._emit(IR.Gep(
            self._new_value(result_type, "decay"),
            ptr,
            [IR.IntConst(self._int_type(), 0), IR.IntConst(self._int_type(), 0)],
            result_type,
        ))

    def _string_global(self, value: str) -> IR.Global:
        if value in self.strings:
            return self.strings[value]
        char_type = self._char_type()
        elem_type = IR.ArrayType(char_type, len(value) + 1)
        global_type = IR.PointerType(elem_type)
        name = f".str.{self.string_id}"
        self.string_id += 1
        global_var = IR.Global(name, global_type, elem_type, IR.StringConst(elem_type, value), True, None)
        self.module.globals.append(global_var)
        self.strings[value] = global_var
        return global_var

    def _string_ptr(self, value: str) -> IR.Operand:
        global_var = self._string_global(value)
        return self._emit(IR.Gep(
            self._new_value(IR.PointerType(self._char_type()), "str"),
            global_var,
            [IR.IntConst(self._int_type(), 0), IR.IntConst(self._int_type(), 0)],
            IR.PointerType(self._char_type()),
        ))

    def _to_bool(self, value: IR.Operand, ctype: AST.CType) -> IR.Operand:
        if isinstance(ctype, AST.PointerType):
            return self._emit(IR.ICmp(self._new_value(self._bool_type(), "ptrbool"), IR.CmpKind.NE, value, IR.NullPtr(self._lower_type(ctype)), False))
        if self._is_float(ctype):
            zero = IR.FloatConst(self._lower_type(ctype), 0.0)
            return self._emit(IR.FCmp(self._new_value(self._bool_type(), "fbool"), IR.CmpKind.NE, value, zero))
        zero = IR.IntConst(self._int_type(), 0)
        return self._emit(IR.ICmp(self._new_value(self._bool_type(), "ibool"), IR.CmpKind.NE, value, zero, self._is_signed(ctype)))

    def _coerce(self, value: IR.Operand, from_type: AST.CType, to_type: AST.CType) -> IR.Operand:
        if self._type_equal(from_type, to_type):
            return value
        from_ir = self._lower_type(from_type)
        to_ir = self._lower_type(to_type)
        kind = self._cast_kind(from_ir, to_ir)
        return self._emit(IR.Cast(self._new_value(to_ir, "cast"), kind, value, to_ir))

    def _cast_kind(self, from_type: IR.Type, to_type: IR.Type) -> IR.CastKind:
        if isinstance(from_type, IR.PointerType) or isinstance(to_type, IR.PointerType):
            return IR.CastKind.PTR if isinstance(from_type, IR.IntType) or isinstance(to_type, IR.IntType) else IR.CastKind.BITCAST
        if isinstance(from_type, IR.FloatType) or isinstance(to_type, IR.FloatType):
            return IR.CastKind.FLOAT
        return IR.CastKind.INT

    def _lower_type(self, ctype: AST.CType) -> IR.Type:
        match ctype:
            case AST.BuiltinType(keywords=keywords):
                names = [kw.name for kw in keywords]
                if "bool" in names:
                    return self._bool_type()
                if "float" in names:
                    return IR.FloatType("float")
                if "double" in names:
                    return IR.FloatType("double")
                return IR.IntType(self._int_bits(names), "unsigned" not in names)
            case AST.VoidType():
                return IR.VoidType()
            case AST.PointerType(base=base):
                return IR.PointerType(self._lower_type(base))
            case AST.ArrayType(base=base, size=size):
                count = size.value if isinstance(size, AST.IntLiteral) else None
                return IR.ArrayType(self._lower_type(base), count)
            case AST.FunctionType(return_type=return_type, params=params, variadic=variadic):
                return IR.FunctionType(self._lower_type(return_type), [self._param_type(param.ctype) for param in params], variadic)
            case AST.StructType(name=name, fields=fields):
                if fields is None:
                    return IR.StructType(name.name if name else None, None)
                ir_fields = [IR.FieldType(field.name.name if field.name else None, self._lower_type(field.ctype)) for field in fields]
                return IR.StructType(name.name if name else None, ir_fields)
            case AST.UnionType(name=name, fields=fields):
                if fields is None:
                    return IR.UnionType(name.name if name else None, None)
                ir_fields = [IR.FieldType(field.name.name if field.name else None, self._lower_type(field.ctype)) for field in fields]
                return IR.UnionType(name.name if name else None, ir_fields)
            case AST.EnumType():
                return self._int_type()
            case AST.NamedType():
                return self._int_type()
        raise ValueError("Unknown type")

    def _param_type(self, ctype: AST.CType) -> IR.Type:
        match ctype:
            case AST.ArrayType(base=base):
                return IR.PointerType(self._lower_type(base))
            case AST.FunctionType():
                return IR.PointerType(self._lower_type(ctype))
        return self._lower_type(ctype)

    def _func_ctype(self, ctype: AST.CType) -> AST.FunctionType:
        match ctype:
            case AST.FunctionType():
                return ctype
            case AST.PointerType(base=base) if isinstance(base, AST.FunctionType):
                return base
        raise ValueError("Expected function type")

    def _int_bits(self, names: list[str]) -> int:
        long_count = sum(1 for name in names if name == "long")
        if "char" in names:
            return 8
        if "short" in names:
            return 16
        if long_count >= 1:
            return 64
        return 32

    def _type_equal(self, left: AST.CType, right: AST.CType) -> bool:
        return self._type_key(left) == self._type_key(right)

    def _type_key(self, ctype: AST.CType) -> tuple:
        match ctype:
            case AST.BuiltinType(keywords=keywords):
                return ("builtin", tuple(sorted(kw.name for kw in keywords)))
            case AST.VoidType():
                return ("void",)
            case AST.PointerType(base=base):
                return ("ptr", self._type_key(base))
            case AST.ArrayType(base=base, size=size):
                size_val = size.value if isinstance(size, AST.IntLiteral) else None
                return ("array", self._type_key(base), size_val)
            case AST.FunctionType(return_type=return_type, params=params, variadic=variadic):
                return ("func", self._type_key(return_type), tuple(self._type_key(p.ctype) for p in params), variadic)
            case AST.StructType(name=name):
                return ("struct", name.name if name else id(ctype))
            case AST.UnionType(name=name):
                return ("union", name.name if name else id(ctype))
            case AST.EnumType(name=name):
                return ("enum", name.name if name else id(ctype))
            case AST.NamedType(name=name):
                return ("named", name.name)
        return ("unknown",)

    def _sizeof(self, ctype: AST.CType) -> int:
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
                return self._sizeof(base) * count
            case AST.StructType(fields=fields):
                return sum(self._sizeof(field.ctype) for field in (fields or []))
            case AST.UnionType(fields=fields):
                return max((self._sizeof(field.ctype) for field in (fields or [])), default=0)
        return 0

    def _is_float(self, ctype: AST.CType) -> bool:
        return isinstance(ctype, AST.BuiltinType) and any(kw.name in {"float", "double"} for kw in ctype.keywords)

    def _is_integer(self, ctype: AST.CType) -> bool:
        return isinstance(ctype, AST.BuiltinType) and any(kw.name in {"bool", "char", "short", "int", "long", "signed", "unsigned"} for kw in ctype.keywords)

    def _is_signed(self, ctype: AST.CType) -> bool:
        if isinstance(ctype, AST.BuiltinType):
            return all(kw.name != "unsigned" for kw in ctype.keywords)
        return True

    def _float_result_type(self, left: AST.CType, right: AST.CType) -> AST.CType:
        if isinstance(left, AST.BuiltinType) and any(kw.name == "double" for kw in left.keywords):
            return left
        if isinstance(right, AST.BuiltinType) and any(kw.name == "double" for kw in right.keywords):
            return right
        return AST.BuiltinType([AST.TypeKeyword("float")])

    def _bool_type(self) -> IR.IntType:
        return IR.IntType(1, False)

    def _int_type(self) -> IR.IntType:
        return IR.IntType(32, True)

    def _int_type_ast(self) -> AST.CType:
        return AST.BuiltinType([AST.TypeKeyword("int")])

    def _char_type(self) -> IR.IntType:
        return IR.IntType(8, True)

    def _zero_const(self, ctype: AST.CType) -> IR.Operand:
        ir_type = self._lower_type(ctype)
        if isinstance(ir_type, IR.FloatType):
            return IR.FloatConst(ir_type, 0.0)
        if isinstance(ir_type, IR.PointerType):
            return IR.NullPtr(ir_type)
        return IR.IntConst(ir_type, 0)

    def _cmp_kind(self, op: str) -> IR.CmpKind:
        return {
            "==": IR.CmpKind.EQ,
            "!=": IR.CmpKind.NE,
            "<": IR.CmpKind.LT,
            "<=": IR.CmpKind.LE,
            ">": IR.CmpKind.GT,
            ">=": IR.CmpKind.GE,
        }[op]

    def _binop_kind(self, op: str) -> IR.BinOpKind:
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

    def _expr_type(self, expr: AST.Expr) -> AST.CType:
        assert expr.expr_type is not None
        return expr.expr_type

    def _current(self) -> IR.BasicBlock:
        assert self.current is not None
        return self.current

    def _new_value(self, ctype: IR.Type, hint: str) -> IR.Value:
        name = f"{hint}.{self.value_id}"
        self.value_id += 1
        return IR.Value(name, ctype)

    def _new_block(self, hint: str) -> IR.BasicBlock:
        name = f"{hint}.{self.block_id}"
        self.block_id += 1
        block = IR.BasicBlock(name)
        self.blocks.append(block)
        if self.current is None:
            self.current = block
        return block

    def _set_current(self, block: IR.BasicBlock) -> None:
        self.current = block

    def _set_term(self, term: IR.Terminator) -> None:
        if self.current is None or self.current.term is not None:
            return
        self.current.term = term

    def _emit(self, instr: IR.Instr) -> IR.Operand:
        assert self.current is not None
        self.current.instrs.append(instr)
        if isinstance(instr, IR.Call):
            return instr.result if instr.result is not None else IR.ZeroInit(self._int_type())
        if isinstance(instr, (IR.BinOp, IR.ICmp, IR.FCmp, IR.Cast, IR.Select, IR.Alloca, IR.Load, IR.Gep)):
            return instr.result
        return IR.ZeroInit(self._int_type())

    def _push_scope(self) -> None:
        self.locals.append({})

    def _pop_scope(self) -> None:
        self.locals.pop()

    def _bind_local(self, name: str, storage: IR.Operand) -> None:
        self.locals[-1][name] = storage

    def _label_block(self, name: str) -> IR.BasicBlock:
        if name not in self.labels:
            self.labels[name] = self._new_block(f"label.{name}")
        return self.labels[name]
