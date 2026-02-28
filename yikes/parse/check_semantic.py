from __future__ import annotations

from dataclasses import dataclass, field

from yikes.parse import ast as AST  # noqa: N812
from yikes.parse.helpers import const_eval, error


@dataclass
class SwitchContext:
    cases: set[int] = field(default_factory=set)
    has_default: bool = False

@dataclass
class SemanticContext:
    label_scope: AST.Scope
    loop_depth: int = 0
    switch_stack: list[SwitchContext] = field(default_factory=list)

def check_semantic(program: AST.Program) -> None:
    for item in program.items:
        _check_external_decl(item)

def _check_block(block: AST.Block, ctx: SemanticContext) -> None:
    for item in block.items:
        _check_stmt(item, ctx)

def _check_external_decl(node: AST.ExternalDecl) -> None:
    match node:
        case AST.FunctionDef():
            ctx = SemanticContext(node.scope)
            _check_block(node.body, ctx)

def _check_stmt(node: AST.Stmt, ctx: SemanticContext) -> None:
    match node:
        case AST.Block():
            _check_block(node, ctx)
        case AST.If(then=then, otherwise=otherwise):
            _check_block(then, ctx)
            if otherwise:
                _check_block(otherwise, ctx)
        case AST.While(body=body):
            ctx.loop_depth += 1
            _check_block(body, ctx)
            ctx.loop_depth -= 1
        case AST.Break():
            if ctx.loop_depth == 0 and not ctx.switch_stack:
                error(node.span, "break not within loop or switch")
        case AST.Continue():
            if ctx.loop_depth == 0:
                error(node.span, "continue not within loop")
        case AST.Switch(body=body):
            ctx.switch_stack.append(SwitchContext())
            _check_block(body, ctx)
            ctx.switch_stack.pop()
        case AST.Case(value=value, body=body):
            if not ctx.switch_stack:
                error(node.span, "case not within switch")
            const = const_eval(value)
            if const is None:
                error(value.span, "case value is not an integer constant expression")
            switch = ctx.switch_stack[-1]
            if const in switch.cases:
                error(value.span, "duplicate case value")
            switch.cases.add(const)
            _check_block(body, ctx)
        case AST.Default(body=body):
            if not ctx.switch_stack:
                error(node.span, "default not within switch")
            switch = ctx.switch_stack[-1]
            if switch.has_default:
                error(node.span, "duplicate default label")
            switch.has_default = True
            _check_block(body, ctx)
        case AST.Label(name=name, stmt=stmt):
            if name.name not in ctx.label_scope.labels:
                error(name.span, f"Unknown label '{name.name}'")
            _check_stmt(stmt, ctx)
        case AST.Goto(target=target):
            if target.name not in ctx.label_scope.labels:
                error(target.span, f"Unknown label '{target.name}'")
