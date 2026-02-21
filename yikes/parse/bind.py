from __future__ import annotations

from yikes.parse import ast as AST  # noqa: N812


def bind(program: AST.Program) -> AST.Program:
    for item in program.items:
        _bind_external_decl(item, program.scope)
    return program

def _bind_external_decl(node: AST.ExternalDecl, scope: AST.Scope) -> None:
    match node:
        case AST.FunctionDef():
            _add_ident(scope, node.name, AST.SymbolKind.FUNC, None, node)
            _bind_params(node.params, node.body.scope)
            _bind_block(node.body, node.body.scope, node.scope, use_existing=True)
        case AST.VarDecl():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, node.name, AST.SymbolKind.VAR, node.ctype, node)
        case AST.TypeDef():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, node.name, AST.SymbolKind.TYPEDEF, node.ctype, node)
        case AST.StructDef():
            _bind_tag_def(scope, AST.StructType(node.name, node.fields), node)
        case AST.UnionDef():
            _bind_tag_def(scope, AST.UnionType(node.name, node.fields), node)
        case AST.EnumDef():
            _bind_tag_def(scope, AST.EnumType(node.name, node.values), node)
            _bind_enumerators(scope, node.values)
        case AST.Declaration():
            _bind_declaration(node, scope)
        case _:
            raise TypeError(f"Unknown external decl: {type(node).__name__}")

def _bind_stmt(node: AST.Stmt, scope: AST.Scope, label_scope: AST.Scope) -> None:
    match node:
        case AST.Block():
            _bind_block(node, scope, label_scope)
        case AST.VarDecl():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, node.name, AST.SymbolKind.VAR, node.ctype, node)
        case AST.TypeDef():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, node.name, AST.SymbolKind.TYPEDEF, node.ctype, node)
        case AST.StructDef():
            _bind_tag_def(scope, AST.StructType(node.name, node.fields), node)
        case AST.UnionDef():
            _bind_tag_def(scope, AST.UnionType(node.name, node.fields), node)
        case AST.EnumDef():
            _bind_tag_def(scope, AST.EnumType(node.name, node.values), node)
            _bind_enumerators(scope, node.values)
        case AST.Declaration():
            _bind_declaration(node, scope)
        case AST.ExprStmt() | AST.Return() | AST.Break() | AST.Continue() | AST.Goto():
            return
        case AST.If():
            _bind_stmt(node.then, scope, label_scope)
            if node.otherwise:
                _bind_stmt(node.otherwise, scope, label_scope)
        case AST.While():
            _bind_stmt(node.body, scope, label_scope)
        case AST.DoWhile():
            _bind_stmt(node.body, scope, label_scope)
        case AST.For():
            for_scope = node.scope
            if node.init:
                _bind_stmt(node.init, for_scope, label_scope)
            _bind_stmt(node.body, for_scope, label_scope)
        case AST.Switch():
            _bind_block(node.body, scope, label_scope)
        case AST.Case():
            _bind_block(node.body, scope, label_scope)
        case AST.Default():
            _bind_block(node.body, scope, label_scope)
        case AST.Label():
            _add_label(label_scope, node.name, node)
            _bind_stmt(node.stmt, scope, label_scope)
        case _:
            raise TypeError(f"Unknown stmt: {type(node).__name__}")

def _bind_block(block: AST.Block, scope: AST.Scope, label_scope: AST.Scope, *, use_existing: bool = False) -> None:
    block_scope = scope if use_existing else block.scope
    for item in block.items:
        _bind_stmt(item, block_scope, label_scope)

def _bind_declaration(node: AST.Declaration, scope: AST.Scope) -> None:
    _bind_decl_specs(node.specs, scope, node)
    is_typedef = _has_storage(node.specs, "typedef")
    kind = AST.SymbolKind.TYPEDEF if is_typedef else AST.SymbolKind.VAR
    for declarator in node.declarators:
        name = _declarator_name(declarator.declarator)
        _add_ident(scope, name, kind, None, node)

def _bind_decl_specs(specs: list[AST.DeclSpec], scope: AST.Scope, owner: AST.SymbolDecl) -> None:
    for spec in specs:
        if isinstance(spec, AST.TypeSpec):
            _bind_ctype_defs(spec.ctype, scope, owner)

def _bind_params(params: list[AST.Param], scope: AST.Scope) -> None:
    for param in params:
        if param.name:
            _add_ident(scope, param.name, AST.SymbolKind.VAR, param.ctype, param)
        _bind_ctype_defs(param.ctype, scope, None)

def _bind_ctype_defs(ctype: AST.CType, scope: AST.Scope, owner: AST.SymbolDecl | None) -> None:
    match ctype:
        case AST.PointerType():
            _bind_ctype_defs(ctype.base, scope, owner)
        case AST.ArrayType():
            _bind_ctype_defs(ctype.base, scope, owner)
        case AST.FunctionType():
            _bind_ctype_defs(ctype.return_type, scope, owner)
            _bind_param_type_defs(ctype.params, scope, owner)
        case AST.StructType() | AST.UnionType() | AST.EnumType():
            _bind_tag_def(scope, ctype, owner)
            if isinstance(ctype, AST.EnumType) and ctype.values is not None:
                _bind_enumerators(scope, ctype.values)
        case AST.BuiltinType() | AST.NamedType():
            return
        case _:
            raise TypeError(f"Unknown ctype: {type(ctype).__name__}")

def _bind_tag_def(scope: AST.Scope, ctype: AST.StructType | AST.UnionType | AST.EnumType, owner: AST.SymbolDecl | None) -> None:
    match ctype:
        case AST.StructType(name=name, fields=fields) if name is not None and fields is not None:
            _add_tag(scope, name, ctype, owner)
        case AST.UnionType(name=name, fields=fields) if name is not None and fields is not None:
            _add_tag(scope, name, ctype, owner)
        case AST.EnumType(name=name, values=values) if name is not None and values is not None:
            _add_tag(scope, name, ctype, owner)

def _bind_enumerators(scope: AST.Scope, values: list[AST.Enumerator]) -> None:
    for value in values:
        _add_ident(scope, value.name, AST.SymbolKind.ENUM_CONST, None, value)

def _bind_param_type_defs(params: list[AST.Param], scope: AST.Scope, owner: AST.SymbolDecl | None) -> None:
    for param in params:
        _bind_ctype_defs(param.ctype, scope, owner)

def _add_ident(scope: AST.Scope, name: str, kind: AST.SymbolKind, ctype: AST.CType | None, decl: AST.SymbolDecl | None) -> None:
    if name and name not in scope.idents:
        scope.idents[name] = AST.Symbol(name, kind, ctype, decl)

def _add_tag(scope: AST.Scope, name: str, ctype: AST.CType, decl: AST.SymbolDecl | None) -> None:
    if name not in scope.tags:
        scope.tags[name] = AST.Symbol(name, AST.SymbolKind.TAG, ctype, decl)

def _add_label(scope: AST.Scope, name: str, decl: AST.Label) -> None:
    if name not in scope.labels:
        scope.labels[name] = AST.Symbol(name, AST.SymbolKind.LABEL, None, decl)

def _has_storage(specs: list[AST.DeclSpec], name: str) -> bool:
    return any(isinstance(spec, AST.StorageClassSpec) and spec.name == name for spec in specs)

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
