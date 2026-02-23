from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple


class Position(NamedTuple):
    line: int
    col: int

class Span(NamedTuple):
    start: Position
    end: Position

class SymbolKind(StrEnum):
    VAR = "var"
    FUNC = "func"
    TYPEDEF = "typedef"
    ENUM_CONST = "enum_const"
    TAG = "tag"
    LABEL = "label"

@dataclass
class Symbol:
    name: str
    kind: SymbolKind
    ctype: CType | None
    decl: SymbolDecl | None

@dataclass
class Scope:
    idents: dict[str, Symbol] = field(default_factory=dict)
    tags: dict[str, Symbol] = field(default_factory=dict)
    labels: dict[str, Symbol] = field(default_factory=dict)


# Intermediate AST nodes

class InitDeclarator(NamedTuple):
    declarator: Declarator
    init: Initializer | None
    span: Span | None = None

class Declarator(NamedTuple):
    pointer: Pointer | None
    direct: DirectDeclarator
    span: Span | None = None

class DirectDeclarator(NamedTuple):
    name: Identifier | None
    nested: Declarator | None
    suffixes: list[DirectSuffix]
    span: Span | None = None

class AbstractDeclarator(NamedTuple):
    pointer: Pointer | None
    direct: DirectAbstractDeclarator | None
    span: Span | None = None

class DirectAbstractDeclarator(NamedTuple):
    nested: AbstractDeclarator | None
    suffixes: list[DirectSuffix]
    span: Span | None = None

class DirectSuffix(NamedTuple):
    params: list[ParamDecl] | None
    array_size: Expr | None
    is_static: bool
    is_variadic: bool
    span: Span | None = None

class ParamDecl(NamedTuple):
    specs: DeclSpecs
    declarator: Declarator | AbstractDeclarator | None
    span: Span | None = None


# Core AST nodes

class Program(NamedTuple):
    items: list[ExternalDecl]
    scope: Scope
    span: Span | None = None

class FunctionDef(NamedTuple):
    name: Identifier
    specs: DeclSpecs
    ctype: FunctionType
    body: Block
    scope: Scope
    span: Span | None = None

class VarDecl(NamedTuple):
    name: Identifier
    ctype: CType
    init: Initializer | None
    span: Span | None = None

class TypeDef(NamedTuple):
    name: Identifier
    ctype: CType
    span: Span | None = None

class DeclSpecs(NamedTuple):
    specs: list[DeclSpec]
    ctype: CType
    span: Span | None = None

class Param(NamedTuple):
    name: Identifier | None
    ctype: CType
    span: Span | None = None

class Block(NamedTuple):
    items: list[Stmt]
    scope: Scope
    span: Span | None = None

class Field(NamedTuple):
    name: Identifier | None
    ctype: CType
    bit_width: Expr | None
    span: Span | None = None

class StructDef(NamedTuple):
    name: Identifier | None
    specs: list[DeclSpec]
    ctype: StructType
    span: Span | None = None

class UnionDef(NamedTuple):
    name: Identifier | None
    specs: list[DeclSpec]
    ctype: UnionType
    span: Span | None = None

class Enumerator(NamedTuple):
    name: Identifier
    value: Expr | None
    span: Span | None = None

class EnumDef(NamedTuple):
    name: Identifier | None
    specs: list[DeclSpec]
    ctype: EnumType
    span: Span | None = None

class Pointer(NamedTuple):
    qualifiers: list[TypeQualifier]
    to: Pointer | None
    span: Span | None = None

class ExprStmt(NamedTuple):
    expr: Expr | None
    span: Span | None = None

class Return(NamedTuple):
    value: Expr | None
    span: Span | None = None

class If(NamedTuple):
    cond: Expr
    then: Block
    otherwise: Block | None
    span: Span | None = None

class While(NamedTuple):
    cond: Expr
    body: Block
    span: Span | None = None

class Break(NamedTuple):
    span: Span | None = None

class Continue(NamedTuple):
    span: Span | None = None

class Switch(NamedTuple):
    expr: Expr
    body: Block
    span: Span | None = None

class Case(NamedTuple):
    value: Expr
    body: Block
    span: Span | None = None

class Default(NamedTuple):
    body: Block
    span: Span | None = None

class Label(NamedTuple):
    name: Identifier
    stmt: Stmt
    span: Span | None = None

class Goto(NamedTuple):
    target: Identifier
    span: Span | None = None

class CompoundLiteral(NamedTuple):
    ctype: CType
    value: Initializer
    span: Span | None = None

class Assign(NamedTuple):
    target: Expr
    value: Expr
    span: Span | None = None

class Binary(NamedTuple):
    op: str
    left: Expr
    right: Expr
    span: Span | None = None

class Unary(NamedTuple):
    op: str
    value: Expr
    span: Span | None = None

class IncDec(NamedTuple):
    op: str
    value: Expr
    is_postfix: bool
    span: Span | None = None

class Call(NamedTuple):
    func: Expr
    args: list[Expr]
    span: Span | None = None

class Member(NamedTuple):
    value: Expr
    name: Identifier
    through_pointer: bool
    span: Span | None = None

class Conditional(NamedTuple):
    cond: Expr
    then: Expr
    otherwise: Expr
    span: Span | None = None

class Cast(NamedTuple):
    target_type: CType
    value: Expr
    span: Span | None = None

class Sizeof(NamedTuple):
    value: Expr | CType
    span: Span | None = None

class IntLiteral(NamedTuple):
    value: int
    span: Span | None = None

class BoolLiteral(NamedTuple):
    value: bool
    span: Span | None = None

class FloatLiteral(NamedTuple):
    value: float
    span: Span | None = None

class CharLiteral(NamedTuple):
    value: str
    span: Span | None = None

class StringLiteral(NamedTuple):
    value: str
    span: Span | None = None

class Identifier(NamedTuple):
    name: str
    span: Span | None = None

class InitList(NamedTuple):
    items: list[InitializerItem]
    span: Span | None = None

class InitializerItem(NamedTuple):
    designators: list[Designator]
    value: Initializer
    span: Span | None = None

class Designator(NamedTuple):
    field: Identifier | None
    index: Expr | None
    span: Span | None = None

class StorageClassSpec(NamedTuple):
    name: str
    span: Span | None = None

class TypeQualifier(NamedTuple):
    name: str
    span: Span | None = None

class FunctionSpec(NamedTuple):
    name: str
    span: Span | None = None

class TypeKeyword(NamedTuple):
    name: str
    span: Span | None = None

class BuiltinType(NamedTuple):
    keywords: list[TypeKeyword]
    span: Span | None = None

class PointerType(NamedTuple):
    base: CType
    span: Span | None = None

class ArrayType(NamedTuple):
    base: CType
    size: Expr | None
    span: Span | None = None

class FunctionType(NamedTuple):
    return_type: CType
    params: list[Param]
    variadic: bool
    span: Span | None = None

class StructType(NamedTuple):
    name: Identifier | None
    fields: list[Field] | None
    span: Span | None = None

class UnionType(NamedTuple):
    name: Identifier | None
    fields: list[Field] | None
    span: Span | None = None

class EnumType(NamedTuple):
    name: Identifier | None
    values: list[Enumerator] | None
    span: Span | None = None

class NamedType(NamedTuple):
    name: Identifier
    span: Span | None = None


Expr = (
    Assign | Binary | Unary | IncDec | Call | Member | Conditional | Cast | Sizeof
    | IntLiteral | BoolLiteral | FloatLiteral | CharLiteral | StringLiteral | Identifier | CompoundLiteral
)
Initializer = Expr | InitList | CompoundLiteral
CType = BuiltinType | PointerType | ArrayType | FunctionType | StructType | UnionType | EnumType | NamedType
DeclSpec = StorageClassSpec | TypeQualifier | FunctionSpec
ExternalDecl = FunctionDef | VarDecl | TypeDef | StructDef | UnionDef | EnumDef
Stmt = (
    Block | VarDecl | TypeDef | StructDef | UnionDef | EnumDef | ExprStmt | Return | If | While | Break
    | Continue | Switch | Case | Default | Label | Goto
)
SymbolDecl = FunctionDef | VarDecl | TypeDef | StructDef | UnionDef | EnumDef | Enumerator | Label | Param
