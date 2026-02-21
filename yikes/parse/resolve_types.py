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
        case AST.VarDecl():
            _set_symbol_ctype(scopes[-1], node.name, _resolve_ctype(node.ctype, scopes))
        case AST.TypeDef():
            _set_symbol_ctype(scopes[-1], node.name, _resolve_ctype(node.ctype, scopes))
        case AST.StructDef():
            _resolve_tag_def(AST.StructType(node.name, node.fields), scopes)
        case AST.UnionDef():
            _resolve_tag_def(AST.UnionType(node.name, node.fields), scopes)
        case AST.EnumDef():
            _resolve_tag_def(AST.EnumType(node.name, node.values), scopes)
        case AST.Declaration():
            _resolve_declaration(node, scopes)
        case _:
            raise TypeError(f"Unknown external decl: {type(node).__name__}")


def _resolve_stmt(node: AST.Stmt, scopes: list[AST.Scope]) -> None:
    match node:
        case AST.Block():
            _resolve_block(node, scopes)
        case AST.VarDecl():
            _set_symbol_ctype(scopes[-1], node.name, _resolve_ctype(node.ctype, scopes))
        case AST.TypeDef():
            _set_symbol_ctype(scopes[-1], node.name, _resolve_ctype(node.ctype, scopes))
        case AST.StructDef():
            _resolve_tag_def(AST.StructType(node.name, node.fields), scopes)
        case AST.UnionDef():
            _resolve_tag_def(AST.UnionType(node.name, node.fields), scopes)
        case AST.EnumDef():
            _resolve_tag_def(AST.EnumType(node.name, node.values), scopes)
        case AST.Declaration():
            _resolve_declaration(node, scopes)
        case AST.ExprStmt() | AST.Return() | AST.Break() | AST.Continue() | AST.Goto():
            return
        case AST.If():
            _resolve_stmt(node.then, scopes)
            if node.otherwise:
                _resolve_stmt(node.otherwise, scopes)
        case AST.While():
            _resolve_stmt(node.body, scopes)
        case AST.DoWhile():
            _resolve_stmt(node.body, scopes)
        case AST.For():
            scopes.append(node.scope)
            if node.init:
                _resolve_stmt(node.init, scopes)
            _resolve_stmt(node.body, scopes)
            scopes.pop()
        case AST.Switch():
            _resolve_block(node.body, scopes)
        case AST.Case():
            _resolve_block(node.body, scopes)
        case AST.Default():
            _resolve_block(node.body, scopes)
        case AST.Label():
            _resolve_stmt(node.stmt, scopes)
        case _:
            raise TypeError(f"Unknown stmt: {type(node).__name__}")


def _resolve_block(block: AST.Block, scopes: list[AST.Scope], *, use_existing: bool = False) -> None:
    if not use_existing:
        scopes.append(block.scope)
    for item in block.items:
        _resolve_stmt(item, scopes)
    if not use_existing:
        scopes.pop()


def _resolve_function_def(node: AST.FunctionDef, scopes: list[AST.Scope]) -> None:
    return_type = _resolve_ctype(node.return_type, scopes)
    params = [_resolve_param(param, scopes) for param in node.params]
    _set_symbol_ctype(scopes[-1], node.name, AST.FunctionType(return_type, params, node.variadic))
    scopes.append(node.body.scope)
    for param in params:
        if param.name:
            _set_symbol_ctype(scopes[-1], param.name, param.ctype)
    _resolve_block(node.body, scopes, use_existing=True)
    scopes.pop()


def _resolve_param(param: AST.Param, scopes: list[AST.Scope]) -> AST.Param:
    return AST.Param(param.name, _resolve_ctype(param.ctype, scopes))


def _resolve_declaration(node: AST.Declaration, scopes: list[AST.Scope]) -> None:
    for declarator in node.declarators:
        name = _declarator_name(declarator.declarator)
        ctype = _build_type(node.specs, declarator.declarator, scopes)
        _set_symbol_ctype(scopes[-1], name, ctype)


def _resolve_tag_def(ctype: AST.StructType | AST.UnionType | AST.EnumType, scopes: list[AST.Scope]) -> None:
    match ctype:
        case AST.StructType(name=name, fields=fields) if name is not None and fields is not None:
            resolved_fields = [_resolve_field(field, scopes) for field in fields]
            _set_tag_ctype(scopes[-1], name, AST.StructType(name, resolved_fields))
        case AST.UnionType(name=name, fields=fields) if name is not None and fields is not None:
            resolved_fields = [_resolve_field(field, scopes) for field in fields]
            _set_tag_ctype(scopes[-1], name, AST.UnionType(name, resolved_fields))
        case AST.EnumType(name=name, values=values) if name is not None and values is not None:
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
            return _resolve_tag_type(ctype, scopes, seen)
        case _:
            raise TypeError(f"Unknown ctype: {type(ctype).__name__}")


def _resolve_named_type(name: str, scopes: list[AST.Scope], seen: set[str] | None) -> AST.CType:
    if seen is None:
        seen = set()
    if name in seen:
        return AST.NamedType(name)
    seen.add(name)
    symbol = _lookup_ident(scopes, name)
    if symbol is None or symbol.kind is not AST.SymbolKind.TYPEDEF or symbol.ctype is None:
        return AST.NamedType(name)
    return _resolve_ctype(symbol.ctype, scopes, seen)


def _resolve_tag_type(
    ctype: AST.StructType | AST.UnionType | AST.EnumType,
    scopes: list[AST.Scope],
    seen: set[str] | None,
) -> AST.CType:
    name = ctype.name
    if name:
        symbol = _lookup_tag(scopes, name)
        if symbol and symbol.ctype is not None:
            if isinstance(ctype, AST.EnumType) and ctype.values is None:
                return symbol.ctype
            if isinstance(ctype, (AST.StructType, AST.UnionType)) and ctype.fields is None:
                return symbol.ctype
    if isinstance(ctype, AST.StructType) and ctype.fields is not None:
        return AST.StructType(name, [_resolve_field(field, scopes) for field in ctype.fields])
    if isinstance(ctype, AST.UnionType) and ctype.fields is not None:
        return AST.UnionType(name, [_resolve_field(field, scopes) for field in ctype.fields])
    return ctype


def _build_type(
    specs: list[AST.DeclSpec],
    declarator: AST.Declarator | AST.AbstractDeclarator | None,
    scopes: list[AST.Scope],
) -> AST.CType:
    base = _base_type(specs, scopes)
    if declarator is None:
        return base
    mods = _collect_mods(declarator)
    for mod in reversed(mods):
        if isinstance(mod, AST.Pointer):
            base = AST.PointerType(base)
        elif mod.array_size is not None or mod.params is None:
            base = AST.ArrayType(base, mod.array_size)
        else:
            params = _build_params(mod.params, scopes)
            base = AST.FunctionType(base, params, mod.is_variadic)
    return _resolve_ctype(base, scopes)


def _build_params(params: list[AST.ParamDecl], scopes: list[AST.Scope]) -> list[AST.Param]:
    items: list[AST.Param] = []
    for param in params:
        if param.declarator is None:
            name = ""
            ctype = _build_type(param.specs, None, scopes)
        elif isinstance(param.declarator, AST.Declarator):
            name = _declarator_name(param.declarator)
            ctype = _build_type(param.specs, param.declarator, scopes)
        else:
            name = ""
            ctype = _build_type(param.specs, param.declarator, scopes)
        items.append(AST.Param(name, ctype))
    return items


def _base_type(specs: list[AST.DeclSpec], scopes: list[AST.Scope]) -> AST.CType:
    for spec in specs:
        if isinstance(spec, AST.TypeSpec):
            return _resolve_ctype(spec.ctype, scopes)
    raise ValueError("Missing type specifier")


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

    if isinstance(decl, AST.Declarator):
        walk_decl(decl)
    else:
        walk_abstract(decl)
    return mods


def _declarator_name(decl: AST.Declarator) -> str:
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
        symbol = scope.idents.get(name)
        if symbol is not None:
            return symbol
    return None


def _lookup_tag(scopes: list[AST.Scope], name: str) -> AST.Symbol | None:
    for scope in reversed(scopes):
        symbol = scope.tags.get(name)
        if symbol is not None:
            return symbol
    return None


def _set_symbol_ctype(scope: AST.Scope, name: str, ctype: AST.CType) -> None:
    symbol = scope.idents.get(name)
    if symbol is None or symbol.ctype is not None:
        return
    symbol.ctype = ctype


def _set_tag_ctype(scope: AST.Scope, name: str, ctype: AST.CType) -> None:
    symbol = scope.tags.get(name)
    if symbol is None:
        return
    symbol.ctype = ctype
