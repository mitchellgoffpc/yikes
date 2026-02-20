from __future__ import annotations

from typing import NamedTuple


class Program(NamedTuple):
    items: list[ExternalDecl]

class FunctionDef(NamedTuple):
    name: str
    params: list[Param]
    return_type: CType
    body: Block

class VarDecl(NamedTuple):
    name: str
    ctype: CType
    init: Expr | None

class TypeDef(NamedTuple):
    name: str
    ctype: CType

class Declaration(NamedTuple):
    specs: list[DeclSpec]
    declarators: list[InitDeclarator]

class Param(NamedTuple):
    name: str
    ctype: CType

class Block(NamedTuple):
    items: list[Stmt]

class Field(NamedTuple):
    name: str | None
    ctype: CType
    bit_width: Expr | None

class StructDef(NamedTuple):
    name: str | None
    fields: list[Field] | None

class UnionDef(NamedTuple):
    name: str | None
    fields: list[Field] | None

class Enumerator(NamedTuple):
    name: str
    value: Expr | None

class EnumDef(NamedTuple):
    name: str | None
    values: list[Enumerator]

class InitDeclarator(NamedTuple):
    declarator: Declarator
    init: Initializer | None

class Declarator(NamedTuple):
    pointer: Pointer | None
    direct: DirectDeclarator

class DirectDeclarator(NamedTuple):
    name: str | None
    nested: Declarator | None
    suffixes: list[DirectSuffix]

class DirectSuffix(NamedTuple):
    params: list[ParamDecl] | None
    array_size: Expr | None
    is_static: bool
    is_variadic: bool

class Pointer(NamedTuple):
    qualifiers: list[TypeQualifier]
    to: Pointer | None

class ParamDecl(NamedTuple):
    specs: list[DeclSpec]
    declarator: Declarator | AbstractDeclarator | None

class AbstractDeclarator(NamedTuple):
    pointer: Pointer | None
    direct: DirectAbstractDeclarator | None

class DirectAbstractDeclarator(NamedTuple):
    nested: AbstractDeclarator | None
    suffixes: list[DirectSuffix]

class ExprStmt(NamedTuple):
    expr: Expr | None

class Return(NamedTuple):
    value: Expr | None

class If(NamedTuple):
    cond: Expr
    then: Stmt
    otherwise: Stmt | None

class While(NamedTuple):
    cond: Expr
    body: Stmt

class DoWhile(NamedTuple):
    body: Stmt
    cond: Expr

class For(NamedTuple):
    init: Stmt | None
    cond: Expr | None
    step: Expr | None
    body: Stmt

class Break(NamedTuple):
    pass

class Continue(NamedTuple):
    pass

class Switch(NamedTuple):
    expr: Expr
    body: Block

class Case(NamedTuple):
    value: Expr
    body: Block

class Default(NamedTuple):
    body: Block

class Label(NamedTuple):
    name: str
    stmt: Stmt

class Goto(NamedTuple):
    target: str

class CompoundLiteral(NamedTuple):
    ctype: CType
    value: Initializer

class Assign(NamedTuple):
    target: Expr
    value: Expr

class Binary(NamedTuple):
    op: str
    left: Expr
    right: Expr

class Unary(NamedTuple):
    op: str
    value: Expr

class IncDec(NamedTuple):
    op: str
    value: Expr
    is_postfix: bool

class Call(NamedTuple):
    func: Expr
    args: list[Expr]

class Member(NamedTuple):
    value: Expr
    name: str
    through_pointer: bool

class ArraySubscript(NamedTuple):
    value: Expr
    index: Expr

class Conditional(NamedTuple):
    cond: Expr
    then: Expr
    otherwise: Expr

class Cast(NamedTuple):
    target_type: CType
    value: Expr

class Sizeof(NamedTuple):
    value: Expr | CType

class IntLiteral(NamedTuple):
    value: int

class BoolLiteral(NamedTuple):
    value: bool

class FloatLiteral(NamedTuple):
    value: float

class CharLiteral(NamedTuple):
    value: str

class StringLiteral(NamedTuple):
    value: str

class Identifier(NamedTuple):
    name: str

class TypeName(NamedTuple):
    ctype: CType

class InitList(NamedTuple):
    items: list[InitializerItem]

class InitializerItem(NamedTuple):
    designators: list[Designator]
    value: Initializer

class Designator(NamedTuple):
    field: str | None
    index: Expr | None

class StorageClassSpec(NamedTuple):
    name: str

class TypeQualifier(NamedTuple):
    name: str

class FunctionSpec(NamedTuple):
    name: str

class TypeSpec(NamedTuple):
    ctype: CType

class BuiltinType(NamedTuple):
    name: str

class PointerType(NamedTuple):
    base: CType

class ArrayType(NamedTuple):
    base: CType
    size: Expr | None

class FunctionType(NamedTuple):
    return_type: CType
    params: list[Param]
    variadic: bool

class StructType(NamedTuple):
    name: str | None
    fields: list[Field] | None

class UnionType(NamedTuple):
    name: str | None
    fields: list[Field] | None

class EnumType(NamedTuple):
    name: str | None
    values: list[Enumerator] | None

class NamedType(NamedTuple):
    name: str

type Expr = (
    Assign | Binary | Unary | IncDec | Call | Member | ArraySubscript | Conditional | Cast | Sizeof
    | IntLiteral | BoolLiteral | FloatLiteral | CharLiteral | StringLiteral | Identifier | CompoundLiteral
)
type Initializer = Expr | InitList | CompoundLiteral
type DeclSpec = StorageClassSpec | TypeQualifier | FunctionSpec | TypeSpec
type CType = BuiltinType | PointerType | ArrayType | FunctionType | StructType | UnionType | EnumType | NamedType
type ExternalDecl = FunctionDef | VarDecl | TypeDef | StructDef | UnionDef | EnumDef | Declaration
type Stmt = (
    Block | VarDecl | Declaration | ExprStmt | Return | If | While | DoWhile | For | Break | Continue
    | Switch | Case | Default | Label | Goto
)


__all__ = [
    "AbstractDeclarator",
    "ArraySubscript",
    "ArrayType",
    "Assign",
    "Binary",
    "BoolLiteral",
    "Block",
    "Break",
    "BuiltinType",
    "Call",
    "Case",
    "Cast",
    "CharLiteral",
    "CompoundLiteral",
    "Conditional",
    "Continue",
    "CType",
    "DeclSpec",
    "Declaration",
    "Declarator",
    "Default",
    "Designator",
    "DirectAbstractDeclarator",
    "DirectDeclarator",
    "DirectSuffix",
    "DoWhile",
    "EnumDef",
    "Enumerator",
    "EnumType",
    "Expr",
    "ExprStmt",
    "ExternalDecl",
    "Field",
    "FloatLiteral",
    "For",
    "FunctionDef",
    "FunctionSpec",
    "FunctionType",
    "Goto",
    "Identifier",
    "If",
    "IncDec",
    "InitDeclarator",
    "InitList",
    "Initializer",
    "InitializerItem",
    "IntLiteral",
    "Label",
    "Member",
    "NamedType",
    "Param",
    "ParamDecl",
    "Pointer",
    "PointerType",
    "Program",
    "Return",
    "Sizeof",
    "StorageClassSpec",
    "StringLiteral",
    "Stmt",
    "StructDef",
    "StructType",
    "Switch",
    "TypeDef",
    "TypeName",
    "TypeQualifier",
    "TypeSpec",
    "Unary",
    "UnionDef",
    "UnionType",
    "VarDecl",
    "While",
]
