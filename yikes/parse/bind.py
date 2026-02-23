from __future__ import annotations

from yikes.parse import ast as AST  # noqa: N812


def bind(program: AST.Program) -> AST.Program:
    for item in program.items:
        _bind_external_decl(item, program.scope)
    return program

def _bind_external_decl(node: AST.ExternalDecl, scope: AST.Scope) -> None:
    match node:
        case AST.FunctionDef():
            _add_ident(scope, AST.SymbolKind.FUNC, None, node)
            _bind_params(node.ctype.params, node.body.scope)
            _bind_block(node.body, node.body.scope, node.scope, use_existing=True)
        case AST.VarDecl():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, AST.SymbolKind.VAR, None, node)
        case AST.TypeDef():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, AST.SymbolKind.TYPEDEF, None, node)
        case AST.StructDef():
            _add_tag(scope, node.ctype, node)
        case AST.UnionDef():
            _add_tag(scope, node.ctype, node)
        case AST.EnumDef():
            _add_tag(scope, node.ctype, node)
            if node.ctype.values is not None:
                _bind_enumerators(scope, node.ctype.values)

def _bind_stmt(node: AST.Stmt, scope: AST.Scope, label_scope: AST.Scope) -> None:
    match node:
        case AST.Block():
            _bind_block(node, scope, label_scope)
        case AST.VarDecl():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, AST.SymbolKind.VAR, None, node)
        case AST.TypeDef():
            _bind_ctype_defs(node.ctype, scope, node)
            _add_ident(scope, AST.SymbolKind.TYPEDEF, None, node)
        case AST.StructDef():
            _add_tag(scope, node.ctype, node)
        case AST.UnionDef():
            _add_tag(scope, node.ctype, node)
        case AST.EnumDef():
            _add_tag(scope, node.ctype, node)
            if node.ctype.values is not None:
                _bind_enumerators(scope, node.ctype.values)
        case AST.ExprStmt() | AST.Return() | AST.Break() | AST.Continue() | AST.Goto():
            return
        case AST.If():
            _bind_stmt(node.then, scope, label_scope)
            if node.otherwise:
                _bind_stmt(node.otherwise, scope, label_scope)
        case AST.While():
            _bind_stmt(node.body, scope, label_scope)
        case AST.Switch():
            _bind_block(node.body, scope, label_scope)
        case AST.Case():
            _bind_block(node.body, scope, label_scope)
        case AST.Default():
            _bind_block(node.body, scope, label_scope)
        case AST.Label():
            _add_label(label_scope, node)
            _bind_stmt(node.stmt, scope, label_scope)

def _bind_block(block: AST.Block, scope: AST.Scope, label_scope: AST.Scope, *, use_existing: bool = False) -> None:
    block_scope = scope if use_existing else block.scope
    for item in block.items:
        _bind_stmt(item, block_scope, label_scope)

def _bind_params(params: list[AST.Param], scope: AST.Scope) -> None:
    for param in params:
        if param.name is not None:
            _add_ident(scope, AST.SymbolKind.VAR, None, param)
        _bind_ctype_defs(param.ctype, scope, None)

def _bind_ctype_defs(ctype: AST.CType, scope: AST.Scope, owner: AST.SymbolDecl | None) -> None:
    match ctype:
        case AST.PointerType():
            _bind_ctype_defs(ctype.base, scope, owner)
        case AST.ArrayType():
            _bind_ctype_defs(ctype.base, scope, owner)
        case AST.FunctionType():
            _bind_ctype_defs(ctype.return_type, scope, owner)
            for param in ctype.params:
                _bind_ctype_defs(param.ctype, scope, owner)
        case AST.StructType():
            _add_tag(scope, ctype, owner)
        case AST.UnionType():
            _add_tag(scope, ctype, owner)
        case AST.EnumType(values=values):
            _add_tag(scope, ctype, owner)
            if values is not None:
                _bind_enumerators(scope, values)
        case AST.BuiltinType() | AST.NamedType():
            return

def _bind_enumerators(scope: AST.Scope, values: list[AST.Enumerator]) -> None:
    for value in values:
        _add_ident(scope, AST.SymbolKind.ENUM_CONST, None, value)

def _add_ident(scope: AST.Scope, kind: AST.SymbolKind, ctype: AST.CType | None, decl: AST.SymbolDecl) -> None:
    if decl.name and decl.name.name not in scope.idents:
        scope.idents[decl.name.name] = AST.Symbol(decl.name.name, kind, ctype, decl)

def _add_tag(scope: AST.Scope, ctype: AST.StructType | AST.UnionType | AST.EnumType, decl: AST.SymbolDecl | None) -> None:
    if ctype.name and ctype.name.name not in scope.tags:
        scope.tags[ctype.name.name] = AST.Symbol(ctype.name.name, AST.SymbolKind.TAG, ctype, decl)

def _add_label(scope: AST.Scope, decl: AST.Label) -> None:
    if decl.name.name not in scope.labels:
        scope.labels[decl.name.name] = AST.Symbol(decl.name.name, AST.SymbolKind.LABEL, None, decl)
