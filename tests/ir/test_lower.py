from __future__ import annotations

from typing import TypedDict

import pytest

from yikes.ir import ir as IR  # noqa: N812
from yikes.ir.lower import lower
from yikes.parse.bind import bind
from yikes.parse.check_types import check_types
from yikes.parse.parse import parse
from yikes.parse.resolve_types import resolve_types


def _lower(source: str) -> IR.Module:
    return lower(check_types(resolve_types(bind(parse(source)))))

def _function(module: IR.Module, name: str) -> IR.Function:
    for func in module.functions:
        if func.name == name:
            return func
    raise AssertionError(f"Missing function {name}")

def _block_with_prefix(func: IR.Function, prefix: str) -> IR.BasicBlock:
    for block in func.blocks:
        if block.name.startswith(prefix):
            return block
    raise AssertionError(f"Missing block with prefix {prefix}")

def _collect_instrs(func: IR.Function, instr_type: type[IR.Instr]) -> list[IR.Instr]:
    instrs: list[IR.Instr] = []
    for block in func.blocks:
        instrs.extend(instr for instr in block.instrs if isinstance(instr, instr_type))
    return instrs


class _GlobalsExpected(TypedDict):
    globals: dict[str, IR.Constant]
    string_count: int


def test_globals_and_string_interning(subtests: pytest.Subtests) -> None:
    cases: list[tuple[str, _GlobalsExpected]] = [
        ("int g = 42; int main() { return g; }",
         {"globals": {"g": IR.IntConst(IR.IntType(32, True), 42)}, "string_count": 0}),
        ('int main() { return "hi" == "hi"; }',
         {"globals": {}, "string_count": 1}),
    ]
    for source, expected in cases:
        with subtests.test(source=source):
            module = _lower(source)
            globals_by_name = {glob.name: glob for glob in module.globals}
            assert len([glob for glob in module.globals if glob.name.startswith(".str.")]) == expected["string_count"]
            for name, init in expected["globals"].items():
                assert name in globals_by_name
                assert globals_by_name[name].init == init


def test_entry_and_default_return() -> None:
    module = _lower("int f() {} void g() {}")
    f = _function(module, "f")
    g = _function(module, "g")
    assert f.blocks[0].name.startswith("entry")
    assert isinstance(f.blocks[-1].term, IR.Ret)
    assert isinstance(g.blocks[-1].term, IR.Ret)
    assert g.blocks[-1].term.value is None


def test_parameters_allocated_and_stored() -> None:
    module = _lower("int add(int x, int y) { return x + y; }")
    func = _function(module, "add")
    instrs = func.blocks[0].instrs
    assert any(isinstance(instr, IR.Alloca) and instr.alloc_type == IR.IntType(32, True) for instr in instrs)
    assert sum(1 for instr in instrs if isinstance(instr, IR.Store)) == 2


def test_if_creates_phi_for_conditional() -> None:
    module = _lower("int f(int x) { return x ? 1 : 2; }")
    func = _function(module, "f")
    end_block = _block_with_prefix(func, "cond.end")
    assert len(end_block.phis) == 1


def test_short_circuit_and_or_phi() -> None:
    module = _lower("int f(int a, int b) { return a && b; }")
    func = _function(module, "f")
    end_block = _block_with_prefix(func, "logic.end")
    assert len(end_block.phis) == 1


def test_switch_lowering_fallthrough_and_default() -> None:
    module = _lower("int f(int x) { switch (x) { case 1: x = 2; default: x = 3; } return x; }")
    func = _function(module, "f")
    switch_terms = [block.term for block in func.blocks if isinstance(block.term, IR.Switch)]
    assert len(switch_terms) == 1
    switch = switch_terms[0]
    assert len(switch.cases) == 1
    assert switch.default.name.startswith("switch.default")


def test_pointer_arithmetic_and_deref() -> None:
    module = _lower("int f(int *p) { return *(p + 1); }")
    func = _function(module, "f")
    geps = _collect_instrs(func, IR.Gep)
    assert geps
    loads = _collect_instrs(func, IR.Load)
    assert loads


def test_member_access_struct_and_union() -> None:
    module = _lower("typedef struct S { int x; int y; } S; typedef union U { int x; char c; } U; int f(S s, U *u) { return s.y + u->x; }")
    func = _function(module, "f")
    geps = _collect_instrs(func, IR.Gep)
    casts = _collect_instrs(func, IR.Cast)
    assert geps
    assert casts


def test_initializer_list_array_and_struct() -> None:
    module = _lower("typedef struct S { int a; int b; } S; int f() { int a[2] = {1, 2}; S s = { .b = 3, .a = 1 }; return a[0] + s.a; }")
    func = _function(module, "f")
    stores = _collect_instrs(func, IR.Store)
    assert len(stores) >= 4


def test_compound_literal_lvalue() -> None:
    module = _lower("typedef struct S { int a; } S; int f() { return ((S){1}).a; }")
    func = _function(module, "f")
    allocas = _collect_instrs(func, IR.Alloca)
    assert allocas
