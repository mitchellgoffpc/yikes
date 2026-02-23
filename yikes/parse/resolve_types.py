from __future__ import annotations

from yikes.parse import ast as AST  # noqa: N812


def resolve_types(program: AST.Program) -> AST.Program:
    scopes: list[AST.Scope] = [program.scope]
    for item in program.items:
        _resolve_external_decl(item, scopes)
    return program

def _resolve_external_decl(node: AST.ExternalDecl, scopes: list[AST.Scope]) -> None:
    match node:
        case AST.FunctionDef():
            _resolve_function_def(node, scopes)
        case AST.VarDecl() | AST.TypeDef():
            _set_symbol_ctype(scopes[-1], node.name, _resolve_ctype(node.ctype, scopes))
        case AST.StructDef():
            _resolve_tag_def(AST.StructType(node.name, node.fields), scopes)
        case AST.UnionDef():
            _resolve_tag_def(AST.UnionType(node.name, node.fields), scopes)
        case AST.EnumDef():
            _resolve_tag_def(AST.EnumType(node.name, node.values), scopes)
        case _:
            raise TypeError(f"Unknown external decl: {type(node).__name__}")

def _resolve_stmt(node: AST.Stmt, scopes: list[AST.Scope]) -> None:
    match node:
        case AST.Block():
            _resolve_block(node, scopes)
        case AST.VarDecl() | AST.TypeDef():
            _set_symbol_ctype(scopes[-1], node.name, _resolve_ctype(node.ctype, scopes))
        case AST.StructDef():
            _resolve_tag_def(AST.StructType(node.name, node.fields), scopes)
        case AST.UnionDef():
            _resolve_tag_def(AST.UnionType(node.name, node.fields), scopes)
        case AST.EnumDef():
            _resolve_tag_def(AST.EnumType(node.name, node.values), scopes)
        case AST.ExprStmt() | AST.Return() | AST.Break() | AST.Continue() | AST.Goto():
            return
        case AST.If():
            _resolve_stmt(node.then, scopes)
            if node.otherwise:
                _resolve_stmt(node.otherwise, scopes)
        case AST.While(body=stmt) | AST.DoWhile(body=stmt) | AST.Label(stmt=stmt):
            _resolve_stmt(stmt, scopes)
        case AST.For():
            scopes = [*scopes, node.scope]
            if node.init:
                _resolve_stmt(node.init, scopes)
            _resolve_stmt(node.body, scopes)
        case AST.Switch() | AST.Case() | AST.Default():
            _resolve_block(node.body, scopes)
        case _:
            raise TypeError(f"Unknown stmt: {type(node).__name__}")

def _resolve_block(block: AST.Block, scopes: list[AST.Scope]) -> None:
    block_scopes = [*scopes, block.scope]
    for item in block.items:
        _resolve_stmt(item, block_scopes)

def _resolve_function_def(node: AST.FunctionDef, scopes: list[AST.Scope]) -> None:
    return_type = _resolve_ctype(node.return_type, scopes)
    params = [_resolve_param(param, scopes) for param in node.params]
    _set_symbol_ctype(scopes[-1], node.name, AST.FunctionType(return_type, params, node.variadic))
    function_scopes = [*scopes, node.body.scope]
    for param in params:
        if param.name is not None:
            _set_symbol_ctype(function_scopes[-1], param.name, param.ctype)
    for item in node.body.items:
        _resolve_stmt(item, function_scopes)

def _resolve_param(param: AST.Param, scopes: list[AST.Scope]) -> AST.Param:
    return AST.Param(param.name, _resolve_ctype(param.ctype, scopes))

def _resolve_tag_def(ctype: AST.StructType | AST.UnionType | AST.EnumType, scopes: list[AST.Scope]) -> None:
    match ctype:
        case AST.StructType(name=name, fields=[*fields]) if name is not None:
            resolved_fields = [_resolve_field(field, scopes) for field in fields]
            _set_tag_ctype(scopes[-1], name, AST.StructType(name, resolved_fields))
        case AST.UnionType(name=name, fields=[*fields]) if name is not None:
            resolved_fields = [_resolve_field(field, scopes) for field in fields]
            _set_tag_ctype(scopes[-1], name, AST.UnionType(name, resolved_fields))
        case AST.EnumType(name=name, values=[*_]) if name is not None:
            _set_tag_ctype(scopes[-1], name, ctype)

def _resolve_field(field: AST.Field, scopes: list[AST.Scope]) -> AST.Field:
    return AST.Field(field.name, _resolve_ctype(field.ctype, scopes), field.bit_width)

def _resolve_ctype(ctype: AST.CType, scopes: list[AST.Scope], seen: set[str] | None = None) -> AST.CType:
    match ctype:
        case AST.BuiltinType():
            return ctype
        case AST.NamedType(name=name):
            return _resolve_named_type(name, scopes, seen)
        case AST.PointerType():
            return AST.PointerType(_resolve_ctype(ctype.base, scopes, seen))
        case AST.ArrayType():
            return AST.ArrayType(_resolve_ctype(ctype.base, scopes, seen), ctype.size)
        case AST.FunctionType():
            return AST.FunctionType(
                _resolve_ctype(ctype.return_type, scopes, seen),
                [_resolve_param(param, scopes) for param in ctype.params],
                ctype.variadic,
            )
        case AST.StructType() | AST.UnionType() | AST.EnumType():
            return _resolve_tag_type(ctype, scopes)
        case _:
            raise TypeError(f"Unknown ctype: {type(ctype).__name__}")

def _resolve_named_type(name: AST.Identifier, scopes: list[AST.Scope], seen: set[str] | None) -> AST.CType:
    if seen is None:
        seen = set()
    if name.name in seen:
        return AST.NamedType(name)
    seen.add(name.name)
    match _lookup_ident(scopes, name.name):
        case AST.Symbol(kind=AST.SymbolKind.TYPEDEF, ctype=ctype) if ctype is not None:
            return _resolve_ctype(ctype, scopes, seen)
    return AST.NamedType(name)

def _resolve_tag_type(ctype: AST.StructType | AST.UnionType | AST.EnumType, scopes: list[AST.Scope]) -> AST.CType:
    if ctype.name is not None:
        symbol = _lookup_tag(scopes, ctype.name.name)
        if symbol and symbol.ctype is not None:
            match ctype:
                case AST.EnumType(values=None) | AST.StructType(fields=None) | AST.UnionType(fields=None):
                    return symbol.ctype
    match ctype:
        case AST.StructType(fields=[*fields]):
            return AST.StructType(ctype.name, [_resolve_field(field, scopes) for field in fields])
        case AST.UnionType(fields=[*fields]):
            return AST.UnionType(ctype.name, [_resolve_field(field, scopes) for field in fields])
    return ctype

def _build_type(specs: AST.DeclSpecs, declarator: AST.Declarator | AST.AbstractDeclarator | None, scopes: list[AST.Scope]) -> AST.CType:
    base = _resolve_ctype(specs.ctype, scopes)
    if declarator is None:
        return base
    for mod in reversed(_collect_mods(declarator)):
        match mod:
            case AST.Pointer():
                base = AST.PointerType(base)
            case AST.DirectSuffix(array_size=None, params=[*params]):
                base = AST.FunctionType(base, [_build_param(param, scopes) for param in params], mod.is_variadic)
            case AST.DirectSuffix(array_size=array_size):
                base = AST.ArrayType(base, array_size)
    return _resolve_ctype(base, scopes)

def _build_param(param: AST.ParamDecl, scopes: list[AST.Scope]) -> AST.Param:
    match param.declarator:
        case None:
            return AST.Param(None, _build_type(param.specs, None, scopes))
        case AST.Declarator():
            return AST.Param(_declarator_name(param.declarator), _build_type(param.specs, param.declarator, scopes))
        case AST.AbstractDeclarator():
            return AST.Param(None, _build_type(param.specs, param.declarator, scopes))

def _collect_mods(decl: AST.Declarator | AST.AbstractDeclarator) -> list[AST.Pointer | AST.DirectSuffix]:
    mods: list[AST.Pointer | AST.DirectSuffix] = []

    def walk_decl(d: AST.Declarator) -> None:
        walk_direct(d.direct)
        p = d.pointer
        while p is not None:
            mods.append(p)
            p = p.to

    def walk_direct(d: AST.DirectDeclarator) -> None:
        if d.nested is not None:
            walk_decl(d.nested)
        for suf in d.suffixes:
            mods.append(suf)

    def walk_abstract(d: AST.AbstractDeclarator) -> None:
        if d.direct is not None:
            walk_direct_abs(d.direct)
        p = d.pointer
        while p is not None:
            mods.append(p)
            p = p.to

    def walk_direct_abs(d: AST.DirectAbstractDeclarator) -> None:
        if d.nested is not None:
            walk_abstract(d.nested)
        for suf in d.suffixes:
            mods.append(suf)

    match decl:
        case AST.Declarator():
            walk_decl(decl)
        case AST.AbstractDeclarator():
            walk_abstract(decl)
    return mods

def _declarator_name(decl: AST.Declarator) -> AST.Identifier:
    direct = decl.direct
    while direct is not None:
        if direct.name is not None:
            return direct.name
        if direct.nested is None:
            break
        decl = direct.nested
        direct = decl.direct
    raise ValueError("Expected declarator name")

def _lookup_ident(scopes: list[AST.Scope], name: str) -> AST.Symbol | None:
    for scope in reversed(scopes):
        if (symbol := scope.idents.get(name)) is not None:
            return symbol
    return None

def _lookup_tag(scopes: list[AST.Scope], name: str) -> AST.Symbol | None:
    for scope in reversed(scopes):
        if (symbol := scope.tags.get(name)) is not None:
            return symbol
    return None

def _set_symbol_ctype(scope: AST.Scope, name: AST.Identifier, ctype: AST.CType) -> None:
    if (symbol := scope.idents.get(name.name)) is not None and symbol.ctype is None:
        symbol.ctype = ctype

def _set_tag_ctype(scope: AST.Scope, name: AST.Identifier, ctype: AST.CType) -> None:
    if (symbol := scope.tags.get(name.name)) is not None:
        symbol.ctype = ctype
