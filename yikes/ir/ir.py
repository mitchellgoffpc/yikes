from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple


class BinOpKind(StrEnum):
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    REM = "rem"
    AND = "and"
    OR = "or"
    XOR = "xor"
    SHL = "shl"
    SHR = "shr"

class CmpKind(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"

class CastKind(StrEnum):
    INT = "int"
    FLOAT = "float"
    PTR = "ptr"
    BITCAST = "bitcast"


class VoidType(NamedTuple):
    pass

class IntType(NamedTuple):
    bits: int
    signed: bool

class FloatType(NamedTuple):
    kind: str

class PointerType(NamedTuple):
    to: Type

class ArrayType(NamedTuple):
    elem: Type
    count: int | None

class FieldType(NamedTuple):
    name: str | None
    type: Type

class StructType(NamedTuple):
    name: str | None
    fields: list[FieldType] | None

class UnionType(NamedTuple):
    name: str | None
    fields: list[FieldType] | None

class FunctionType(NamedTuple):
    return_type: Type
    params: list[Type]
    variadic: bool

class Value(NamedTuple):
    name: str
    type: Type

class IntConst(NamedTuple):
    type: Type
    value: int

class FloatConst(NamedTuple):
    type: Type
    value: float

class BoolConst(NamedTuple):
    type: Type
    value: bool

class CharConst(NamedTuple):
    type: Type
    value: str

class NullPtr(NamedTuple):
    type: Type

class ZeroInit(NamedTuple):
    type: Type

class StringConst(NamedTuple):
    type: Type
    value: str

class AggregateConst(NamedTuple):
    type: Type
    items: list[Constant]

class Global(NamedTuple):
    name: str
    type: Type
    element_type: Type
    init: Constant | None
    is_const: bool
    linkage: str | None

class Param(NamedTuple):
    name: str
    type: Type

class BinOp(NamedTuple):
    result: Value
    op: BinOpKind
    left: Operand
    right: Operand

class ICmp(NamedTuple):
    result: Value
    op: CmpKind
    left: Operand
    right: Operand
    signed: bool

class FCmp(NamedTuple):
    result: Value
    op: CmpKind
    left: Operand
    right: Operand

class Cast(NamedTuple):
    result: Value
    op: CastKind
    value: Operand
    target_type: Type

class Phi(NamedTuple):
    result: Value
    incomings: list[tuple[str, Operand]]

class Select(NamedTuple):
    result: Value
    cond: Operand
    then_value: Operand
    otherwise_value: Operand

class Alloca(NamedTuple):
    result: Value
    alloc_type: Type

class Load(NamedTuple):
    result: Value
    ptr: Operand

class Store(NamedTuple):
    ptr: Operand
    value: Operand

class Gep(NamedTuple):
    result: Value
    base_ptr: Operand
    indices: list[Operand]
    result_type: Type

class Call(NamedTuple):
    result: Value | None
    func: Operand
    args: list[Operand]

class Br(NamedTuple):
    target: str

class CondBr(NamedTuple):
    cond: Operand
    then_target: str
    otherwise_target: str

class SwitchCase(NamedTuple):
    value: Constant
    target: str

class Switch(NamedTuple):
    value: Operand
    default: str
    cases: list[SwitchCase]

class Ret(NamedTuple):
    value: Operand | None

class Unreachable(NamedTuple):
    pass

class BasicBlock(NamedTuple):
    name: str
    phis: list[Phi]
    instrs: list[Instr]
    term: Terminator | None

class Function(NamedTuple):
    name: str
    type: FunctionType
    params: list[Param]
    blocks: list[BasicBlock]

class Module(NamedTuple):
    globals: list[Global]
    functions: list[Function]


Type = VoidType | IntType | FloatType | PointerType | ArrayType | StructType | UnionType | FunctionType
Constant = IntConst | FloatConst | BoolConst | CharConst | NullPtr | ZeroInit | StringConst | AggregateConst
Instr = BinOp | ICmp | FCmp | Cast | Phi | Select | Alloca | Load | Store | Gep | Call
Terminator = Br | CondBr | Switch | Ret | Unreachable
Operand = Value | Global | Param | Constant
