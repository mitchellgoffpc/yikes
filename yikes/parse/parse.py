from __future__ import annotations

from typing import NoReturn

from yikes.lex.lex import Token, lex
from yikes.lex.tokens import TokenKind
from yikes.parse import ast as AST  # noqa: N812

_STORAGE_CLASS = {
    TokenKind.KW_AUTO: "auto",
    TokenKind.KW_EXTERN: "extern",
    TokenKind.KW_REGISTER: "register",
    TokenKind.KW_STATIC: "static",
    TokenKind.KW_TYPEDEF: "typedef",
}
_TYPE_QUAL = {
    TokenKind.KW_CONST: "const",
    TokenKind.KW_VOLATILE: "volatile",
    TokenKind.KW_RESTRICT: "restrict",
}
_FUNC_SPEC = {TokenKind.KW_INLINE: "inline"}
_BUILTIN_TYPES = {
    TokenKind.KW_VOID: "void",
    TokenKind.KW_CHAR: "char",
    TokenKind.KW_SHORT: "short",
    TokenKind.KW_INT: "int",
    TokenKind.KW_LONG: "long",
    TokenKind.KW_FLOAT: "float",
    TokenKind.KW_DOUBLE: "double",
    TokenKind.KW_SIGNED: "signed",
    TokenKind.KW_UNSIGNED: "unsigned",
    TokenKind.KW_BOOL: "_Bool",
    TokenKind.KW_COMPLEX: "_Complex",
    TokenKind.KW_IMAGINARY: "_Imaginary",
}
_ASSIGN_OPS: dict[TokenKind, str] = {
    TokenKind.ASSIGN: "=",
    TokenKind.PLUS_ASSIGN: "+=",
    TokenKind.MINUS_ASSIGN: "-=",
    TokenKind.STAR_ASSIGN: "*=",
    TokenKind.SLASH_ASSIGN: "/=",
    TokenKind.PERCENT_ASSIGN: "%=",
    TokenKind.AMP_ASSIGN: "&=",
    TokenKind.PIPE_ASSIGN: "|=",
    TokenKind.CARET_ASSIGN: "^=",
    TokenKind.LSHIFT_ASSIGN: "<<=",
    TokenKind.RSHIFT_ASSIGN: ">>=",
}


def parse(source: str) -> AST.Program:
    tokens = lex(source)
    pos = 0
    typedef_names: set[str] = set()

    def peek(offset: int = 0) -> Token:
        i = pos + offset
        if i < 0:
            i = 0
        if i >= len(tokens):
            return tokens[-1]
        return tokens[i]

    def at(kind: TokenKind) -> bool:
        return peek().kind == kind

    def at_any(kinds: set[TokenKind]) -> bool:
        return peek().kind in kinds

    def advance() -> Token:
        nonlocal pos
        tok = peek()
        pos = min(pos + 1, len(tokens))
        return tok

    def match(kind: TokenKind) -> bool:
        if at(kind):
            advance()
            return True
        return False

    def expect(kind: TokenKind) -> Token:
        if not at(kind):
            error(f"Expected {kind.value}")
        return advance()

    def match_ident() -> str | None:
        if at(TokenKind.IDENT):
            value = advance().value
            assert isinstance(value, str)
            return value
        return None

    def expect_ident() -> str:
        if not at(TokenKind.IDENT):
            error("Expected identifier")
        value = advance().value
        assert isinstance(value, str)
        return value

    def error(message: str) -> NoReturn:
        tok = peek()
        raise ValueError(f"{message} at {tok.line}:{tok.col}")

    def is_decl_start() -> bool:
        tok = peek()
        return (
            tok.kind in _STORAGE_CLASS
            or tok.kind in _TYPE_QUAL
            or tok.kind in _FUNC_SPEC
            or tok.kind in _BUILTIN_TYPES
            or tok.kind in {TokenKind.KW_STRUCT, TokenKind.KW_UNION, TokenKind.KW_ENUM}
            or (tok.kind == TokenKind.IDENT and tok.value in typedef_names)
        )

    def looks_like_type_name() -> bool:
        if at(TokenKind.LPAREN):
            if pos + 1 >= len(tokens):
                return False
            next_tok = tokens[pos + 1]
            return (
                next_tok.kind in _STORAGE_CLASS
                or next_tok.kind in _TYPE_QUAL
                or next_tok.kind in _FUNC_SPEC
                or next_tok.kind in _BUILTIN_TYPES
                or next_tok.kind in {TokenKind.KW_STRUCT, TokenKind.KW_UNION, TokenKind.KW_ENUM}
                or (next_tok.kind == TokenKind.IDENT and next_tok.value in typedef_names)
            )
        return is_decl_start()

    def looks_like_abstract_declarator() -> bool:
        return peek().kind in {TokenKind.STAR, TokenKind.LPAREN, TokenKind.LBRACKET}

    def looks_like_named_declarator() -> bool:
        i = pos
        while i < len(tokens):
            kind = tokens[i].kind
            if kind == TokenKind.IDENT:
                return True
            if kind in {TokenKind.COMMA, TokenKind.RPAREN, TokenKind.RBRACKET, TokenKind.SEMI}:
                return False
            i += 1
        return False

    def has_storage(specs: list[AST.DeclSpec], name: str) -> bool:
        return any(isinstance(s, AST.StorageClassSpec) and s.name == name for s in specs)

    def is_void_param(specs: list[AST.DeclSpec], decl: AST.Declarator | AST.AbstractDeclarator | None, params: list[AST.ParamDecl]) -> bool:
        if decl is not None or params:
            return False
        if len(specs) != 1:
            return False
        spec = specs[0]
        return isinstance(spec, AST.TypeSpec) and isinstance(spec.ctype, AST.BuiltinType) and spec.ctype.name == "void"

    def parse_program() -> AST.Program:
        items: list[AST.ExternalDecl] = []
        while not at(TokenKind.EOF):
            items.append(parse_external_decl())
        return AST.Program(items, scope=AST.Scope())

    def parse_external_decl() -> AST.ExternalDecl:
        specs = parse_decl_specs()
        if match(TokenKind.SEMI):
            tag_def = extract_tag_def(specs)
            return tag_def or AST.Declaration(specs, [])

        decls = parse_init_declarator_list()
        if at(TokenKind.LBRACE):
            if len(decls) != 1 or decls[0].init is not None:
                error("Invalid function definition")
            name = declarator_name(decls[0].declarator)
            ctype = build_type(specs, decls[0].declarator)
            if not isinstance(ctype, AST.FunctionType):
                error("Function definition requires function type")
            assert isinstance(ctype, AST.FunctionType)
            body = parse_block()
            return AST.FunctionDef(name, ctype.params, ctype.return_type, ctype.variadic, body, scope=AST.Scope())

        expect(TokenKind.SEMI)
        if has_storage(specs, "typedef"):
            if len(decls) == 1 and decls[0].init is None:
                name = declarator_name(decls[0].declarator)
                ctype = build_type(specs, decls[0].declarator)
                typedef_names.add(name)
                return AST.TypeDef(name, ctype)
            return AST.Declaration(specs, decls)

        if len(decls) == 1:
            name = declarator_name(decls[0].declarator)
            ctype = build_type(specs, decls[0].declarator)
            return AST.VarDecl(name, ctype, decls[0].init)
        return AST.Declaration(specs, decls)

    def parse_block() -> AST.Block:
        expect(TokenKind.LBRACE)
        items: list[AST.Stmt] = []
        while not at(TokenKind.RBRACE):
            if at(TokenKind.KW_CASE):
                items.append(parse_case())
                continue
            if at(TokenKind.KW_DEFAULT):
                items.append(parse_default())
                continue
            if is_decl_start():
                items.append(parse_declaration())
                continue
            items.append(parse_stmt())
        expect(TokenKind.RBRACE)
        return AST.Block(items, scope=AST.Scope())

    def parse_stmt() -> AST.Stmt:
        if at(TokenKind.LBRACE):
            return parse_block()
        if match(TokenKind.KW_RETURN):
            value = None if at(TokenKind.SEMI) else parse_expr()
            expect(TokenKind.SEMI)
            return AST.Return(value)
        if match(TokenKind.KW_IF):
            expect(TokenKind.LPAREN)
            cond = parse_expr()
            expect(TokenKind.RPAREN)
            then = parse_stmt()
            otherwise = parse_stmt() if match(TokenKind.KW_ELSE) else None
            return AST.If(cond, then, otherwise)
        if match(TokenKind.KW_WHILE):
            expect(TokenKind.LPAREN)
            cond = parse_expr()
            expect(TokenKind.RPAREN)
            return AST.While(cond, parse_stmt())
        if match(TokenKind.KW_DO):
            body = parse_stmt()
            expect(TokenKind.KW_WHILE)
            expect(TokenKind.LPAREN)
            cond = parse_expr()
            expect(TokenKind.RPAREN)
            expect(TokenKind.SEMI)
            return AST.DoWhile(body, cond)
        if match(TokenKind.KW_FOR):
            return parse_for()
        if match(TokenKind.KW_BREAK):
            expect(TokenKind.SEMI)
            return AST.Break()
        if match(TokenKind.KW_CONTINUE):
            expect(TokenKind.SEMI)
            return AST.Continue()
        if match(TokenKind.KW_SWITCH):
            expect(TokenKind.LPAREN)
            expr = parse_expr()
            expect(TokenKind.RPAREN)
            body = parse_block()
            return AST.Switch(expr, body)
        if match(TokenKind.KW_GOTO):
            target = expect_ident()
            expect(TokenKind.SEMI)
            return AST.Goto(target)
        if at(TokenKind.IDENT) and peek(1).kind == TokenKind.COLON:
            name = expect_ident()
            expect(TokenKind.COLON)
            return AST.Label(name, parse_stmt())

        expr = None if at(TokenKind.SEMI) else parse_expr()
        expect(TokenKind.SEMI)
        return AST.ExprStmt(expr)

    def parse_case() -> AST.Case:
        expect(TokenKind.KW_CASE)
        value = parse_expr()
        expect(TokenKind.COLON)
        body = AST.Block(parse_stmt_list({TokenKind.KW_CASE, TokenKind.KW_DEFAULT, TokenKind.RBRACE}), scope=AST.Scope())
        return AST.Case(value, body)

    def parse_default() -> AST.Default:
        expect(TokenKind.KW_DEFAULT)
        expect(TokenKind.COLON)
        body = AST.Block(parse_stmt_list({TokenKind.KW_CASE, TokenKind.KW_DEFAULT, TokenKind.RBRACE}), scope=AST.Scope())
        return AST.Default(body)

    def parse_stmt_list(stop: set[TokenKind]) -> list[AST.Stmt]:
        items: list[AST.Stmt] = []
        while not at_any(stop):
            if is_decl_start():
                items.append(parse_declaration())
            else:
                items.append(parse_stmt())
        return items

    def parse_for() -> AST.For:
        expect(TokenKind.LPAREN)
        if match(TokenKind.SEMI):
            init = None
        elif is_decl_start():
            init = parse_declaration()
        else:
            init = AST.ExprStmt(parse_expr())
            expect(TokenKind.SEMI)

        if match(TokenKind.SEMI):
            cond = None
        else:
            cond = parse_expr()
            expect(TokenKind.SEMI)

        step = None if at(TokenKind.RPAREN) else parse_expr()
        expect(TokenKind.RPAREN)
        return AST.For(init, cond, step, parse_stmt(), scope=AST.Scope())

    def parse_declaration() -> AST.Stmt:
        specs = parse_decl_specs()
        if match(TokenKind.SEMI):
            return extract_tag_def(specs) or AST.Declaration(specs, [])
        decls = parse_init_declarator_list()
        expect(TokenKind.SEMI)

        if has_storage(specs, "typedef"):
            if len(decls) == 1 and decls[0].init is None:
                name = declarator_name(decls[0].declarator)
                ctype = build_type(specs, decls[0].declarator)
                typedef_names.add(name)
                return AST.TypeDef(name, ctype)
            return AST.Declaration(specs, decls)

        if len(decls) == 1:
            name = declarator_name(decls[0].declarator)
            ctype = build_type(specs, decls[0].declarator)
            return AST.VarDecl(name, ctype, decls[0].init)
        return AST.Declaration(specs, decls)

    def parse_decl_specs(allow_storage: bool = True, allow_function: bool = True) -> list[AST.DeclSpec]:
        specs: list[AST.DeclSpec] = []
        builtins: list[str] = []
        seen_type_spec = False

        while True:
            tok = peek()
            if tok.kind in _STORAGE_CLASS:
                if not allow_storage:
                    error("Storage class not allowed here")
                specs.append(AST.StorageClassSpec(_STORAGE_CLASS[tok.kind]))
                advance()
                continue
            if tok.kind in _TYPE_QUAL:
                specs.append(AST.TypeQualifier(_TYPE_QUAL[tok.kind]))
                advance()
                continue
            if tok.kind in _FUNC_SPEC:
                if not allow_function:
                    error("Function specifier not allowed here")
                specs.append(AST.FunctionSpec(_FUNC_SPEC[tok.kind]))
                advance()
                continue
            if tok.kind in _BUILTIN_TYPES:
                builtins.append(_BUILTIN_TYPES[tok.kind])
                advance()
                continue
            if tok.kind == TokenKind.KW_STRUCT:
                specs.append(AST.TypeSpec(parse_struct_type()))
                seen_type_spec = True
                continue
            if tok.kind == TokenKind.KW_UNION:
                specs.append(AST.TypeSpec(parse_union_type()))
                seen_type_spec = True
                continue
            if tok.kind == TokenKind.KW_ENUM:
                specs.append(AST.TypeSpec(parse_enum_type()))
                seen_type_spec = True
                continue
            if tok.kind == TokenKind.IDENT and tok.value in typedef_names:
                assert isinstance(tok.value, str)
                specs.append(AST.TypeSpec(AST.NamedType(tok.value)))
                advance()
                seen_type_spec = True
                continue
            break

        if builtins:
            if seen_type_spec:
                error("Multiple type specifiers")
            specs.append(AST.TypeSpec(AST.BuiltinType(" ".join(builtins))))
            seen_type_spec = True

        if not seen_type_spec:
            error("Expected type specifier")
        return specs

    def parse_struct_type() -> AST.StructType:
        expect(TokenKind.KW_STRUCT)
        name = match_ident()
        if match(TokenKind.LBRACE):
            fields = parse_struct_fields()
            expect(TokenKind.RBRACE)
            return AST.StructType(name, fields)
        return AST.StructType(name, None)

    def parse_union_type() -> AST.UnionType:
        expect(TokenKind.KW_UNION)
        name = match_ident()
        if match(TokenKind.LBRACE):
            fields = parse_struct_fields()
            expect(TokenKind.RBRACE)
            return AST.UnionType(name, fields)
        return AST.UnionType(name, None)

    def parse_enum_type() -> AST.EnumType:
        expect(TokenKind.KW_ENUM)
        name = match_ident()
        if match(TokenKind.LBRACE):
            values: list[AST.Enumerator] = []
            while not at(TokenKind.RBRACE):
                enum_name = expect_ident()
                value = parse_expr() if match(TokenKind.ASSIGN) else None
                values.append(AST.Enumerator(enum_name, value))
                if not match(TokenKind.COMMA):
                    break
            expect(TokenKind.RBRACE)
            return AST.EnumType(name, values)
        return AST.EnumType(name, None)

    def parse_struct_fields() -> list[AST.Field]:
        fields: list[AST.Field] = []
        while not at(TokenKind.RBRACE):
            specs = parse_decl_specs(allow_storage=False, allow_function=False)
            if match(TokenKind.SEMI):
                continue
            while True:
                if match(TokenKind.COLON):
                    bit_width = parse_expr()
                    ctype = build_type(specs, None)
                    fields.append(AST.Field(None, ctype, bit_width))
                else:
                    decl = parse_declarator()
                    bit_width = parse_expr() if match(TokenKind.COLON) else None
                    name = declarator_name(decl)
                    ctype = build_type(specs, decl)
                    fields.append(AST.Field(name, ctype, bit_width))
                if not match(TokenKind.COMMA):
                    break
            expect(TokenKind.SEMI)
        return fields

    def parse_init_declarator_list() -> list[AST.InitDeclarator]:
        items: list[AST.InitDeclarator] = []
        while True:
            decl = parse_declarator()
            init = parse_initializer() if match(TokenKind.ASSIGN) else None
            items.append(AST.InitDeclarator(decl, init))
            if not match(TokenKind.COMMA):
                break
        return items

    def parse_declarator() -> AST.Declarator:
        pointer = parse_pointer()
        direct = parse_direct_declarator()
        return AST.Declarator(pointer, direct)

    def parse_direct_declarator() -> AST.DirectDeclarator:
        name: str | None = None
        nested: AST.Declarator | None = None
        if at(TokenKind.IDENT):
            name = expect_ident()
        elif match(TokenKind.LPAREN):
            nested = parse_declarator()
            expect(TokenKind.RPAREN)
        else:
            error("Expected declarator")

        suffixes: list[AST.DirectSuffix] = []
        while True:
            if match(TokenKind.LPAREN):
                params, is_variadic = parse_param_list()
                expect(TokenKind.RPAREN)
                suffixes.append(AST.DirectSuffix(params, None, False, is_variadic))
                continue
            if match(TokenKind.LBRACKET):
                is_static = match(TokenKind.KW_STATIC)
                size = None if at(TokenKind.RBRACKET) else parse_expr()
                expect(TokenKind.RBRACKET)
                suffixes.append(AST.DirectSuffix(None, size, is_static, False))
                continue
            break

        return AST.DirectDeclarator(name, nested, suffixes)

    def parse_abstract_declarator() -> AST.AbstractDeclarator:
        pointer = parse_pointer()
        direct = parse_direct_abstract_declarator()
        return AST.AbstractDeclarator(pointer, direct)

    def parse_direct_abstract_declarator() -> AST.DirectAbstractDeclarator | None:
        nested: AST.AbstractDeclarator | None = None
        suffixes: list[AST.DirectSuffix] = []

        if match(TokenKind.LPAREN):
            if not at(TokenKind.RPAREN):
                nested = parse_abstract_declarator()
            expect(TokenKind.RPAREN)

        while True:
            if match(TokenKind.LPAREN):
                params, is_variadic = parse_param_list()
                expect(TokenKind.RPAREN)
                suffixes.append(AST.DirectSuffix(params, None, False, is_variadic))
                continue
            if match(TokenKind.LBRACKET):
                is_static = match(TokenKind.KW_STATIC)
                size = None if at(TokenKind.RBRACKET) else parse_expr()
                expect(TokenKind.RBRACKET)
                suffixes.append(AST.DirectSuffix(None, size, is_static, False))
                continue
            break

        if nested is None and not suffixes:
            return None
        return AST.DirectAbstractDeclarator(nested, suffixes)

    def parse_pointer() -> AST.Pointer | None:
        if not match(TokenKind.STAR):
            return None
        qualifiers: list[AST.TypeQualifier] = []
        while peek().kind in _TYPE_QUAL:
            qualifiers.append(AST.TypeQualifier(_TYPE_QUAL[peek().kind]))
            advance()
        return AST.Pointer(qualifiers, parse_pointer())

    def parse_param_list() -> tuple[list[AST.ParamDecl], bool]:
        if at(TokenKind.RPAREN):
            return [], False

        params: list[AST.ParamDecl] = []
        is_variadic = False
        while True:
            if match(TokenKind.ELLIPSIS):
                is_variadic = True
                break
            specs = parse_decl_specs(allow_storage=False, allow_function=False)
            decl = None
            if not at_any({TokenKind.COMMA, TokenKind.RPAREN}):
                decl = parse_declarator() if looks_like_named_declarator() else parse_abstract_declarator()
            if is_void_param(specs, decl, params):
                params = []
                break
            params.append(AST.ParamDecl(specs, decl))
            if match(TokenKind.COMMA):
                continue
            break
        return params, is_variadic

    def parse_initializer() -> AST.Initializer:
        if not at(TokenKind.LBRACE):
            return parse_assign_expr()
        expect(TokenKind.LBRACE)
        items: list[AST.InitializerItem] = []
        while not at(TokenKind.RBRACE):
            designators = parse_designators()
            if designators and match(TokenKind.ASSIGN):
                pass
            value = parse_initializer()
            items.append(AST.InitializerItem(designators, value))
            if not match(TokenKind.COMMA):
                break
        expect(TokenKind.RBRACE)
        return AST.InitList(items)

    def parse_designators() -> list[AST.Designator]:
        items: list[AST.Designator] = []
        while True:
            if match(TokenKind.DOT):
                items.append(AST.Designator(expect_ident(), None))
                continue
            if match(TokenKind.LBRACKET):
                index = parse_expr()
                expect(TokenKind.RBRACKET)
                items.append(AST.Designator(None, index))
                continue
            break
        return items

    def parse_expr() -> AST.Expr:
        return parse_comma_expr()

    def parse_comma_expr() -> AST.Expr:
        expr = parse_assign_expr()
        while match(TokenKind.COMMA):
            expr = AST.Binary(",", expr, parse_assign_expr())
        return expr

    def parse_assign_expr() -> AST.Expr:
        expr = parse_conditional_expr()
        if peek().kind in _ASSIGN_OPS:
            op = advance().kind
            value = parse_assign_expr()
            if op == TokenKind.ASSIGN:
                return AST.Assign(expr, value)
            return AST.Assign(expr, AST.Binary(_ASSIGN_OPS[op][:-1], expr, value))
        return expr

    def parse_conditional_expr() -> AST.Expr:
        expr = parse_logical_or()
        if match(TokenKind.QUESTION):
            then = parse_expr()
            expect(TokenKind.COLON)
            otherwise = parse_conditional_expr()
            return AST.Conditional(expr, then, otherwise)
        return expr

    def parse_logical_or() -> AST.Expr:
        expr = parse_logical_and()
        while match(TokenKind.OR_OR):
            expr = AST.Binary("||", expr, parse_logical_and())
        return expr

    def parse_logical_and() -> AST.Expr:
        expr = parse_bitwise_or()
        while match(TokenKind.AND_AND):
            expr = AST.Binary("&&", expr, parse_bitwise_or())
        return expr

    def parse_bitwise_or() -> AST.Expr:
        expr = parse_bitwise_xor()
        while match(TokenKind.PIPE):
            expr = AST.Binary("|", expr, parse_bitwise_xor())
        return expr

    def parse_bitwise_xor() -> AST.Expr:
        expr = parse_bitwise_and()
        while match(TokenKind.CARET):
            expr = AST.Binary("^", expr, parse_bitwise_and())
        return expr

    def parse_bitwise_and() -> AST.Expr:
        expr = parse_equality()
        while match(TokenKind.AMP):
            expr = AST.Binary("&", expr, parse_equality())
        return expr

    def parse_equality() -> AST.Expr:
        expr = parse_relational()
        while True:
            if match(TokenKind.EQ):
                expr = AST.Binary("==", expr, parse_relational())
            elif match(TokenKind.NE):
                expr = AST.Binary("!=", expr, parse_relational())
            else:
                break
        return expr

    def parse_relational() -> AST.Expr:
        expr = parse_shift()
        while True:
            if match(TokenKind.LT):
                expr = AST.Binary("<", expr, parse_shift())
            elif match(TokenKind.GT):
                expr = AST.Binary(">", expr, parse_shift())
            elif match(TokenKind.LE):
                expr = AST.Binary("<=", expr, parse_shift())
            elif match(TokenKind.GE):
                expr = AST.Binary(">=", expr, parse_shift())
            else:
                break
        return expr

    def parse_shift() -> AST.Expr:
        expr = parse_additive()
        while True:
            if match(TokenKind.LSHIFT):
                expr = AST.Binary("<<", expr, parse_additive())
            elif match(TokenKind.RSHIFT):
                expr = AST.Binary(">>", expr, parse_additive())
            else:
                break
        return expr

    def parse_additive() -> AST.Expr:
        expr = parse_multiplicative()
        while True:
            if match(TokenKind.PLUS):
                expr = AST.Binary("+", expr, parse_multiplicative())
            elif match(TokenKind.MINUS):
                expr = AST.Binary("-", expr, parse_multiplicative())
            else:
                break
        return expr

    def parse_multiplicative() -> AST.Expr:
        expr = parse_unary()
        while True:
            if match(TokenKind.STAR):
                expr = AST.Binary("*", expr, parse_unary())
            elif match(TokenKind.SLASH):
                expr = AST.Binary("/", expr, parse_unary())
            elif match(TokenKind.PERCENT):
                expr = AST.Binary("%", expr, parse_unary())
            else:
                break
        return expr

    def parse_unary() -> AST.Expr:
        if match(TokenKind.PLUS_PLUS):
            return AST.IncDec("++", parse_unary(), False)
        if match(TokenKind.MINUS_MINUS):
            return AST.IncDec("--", parse_unary(), False)
        if match(TokenKind.PLUS):
            return AST.Unary("+", parse_unary())
        if match(TokenKind.MINUS):
            return AST.Unary("-", parse_unary())
        if match(TokenKind.BANG):
            return AST.Unary("!", parse_unary())
        if match(TokenKind.TILDE):
            return AST.Unary("~", parse_unary())
        if match(TokenKind.STAR):
            return AST.Unary("*", parse_unary())
        if match(TokenKind.AMP):
            return AST.Unary("&", parse_unary())
        if match(TokenKind.KW_SIZEOF):
            if match(TokenKind.LPAREN) and looks_like_type_name():
                ctype = parse_type_name()
                expect(TokenKind.RPAREN)
                return AST.Sizeof(ctype)
            if peek(-1).kind == TokenKind.LPAREN:
                error("Expected type name")
            return AST.Sizeof(parse_unary())

        if at(TokenKind.LPAREN) and looks_like_type_name():
            expect(TokenKind.LPAREN)
            ctype = parse_type_name()
            expect(TokenKind.RPAREN)
            if at(TokenKind.LBRACE):
                init = parse_initializer()
                return AST.CompoundLiteral(ctype, init)
            return AST.Cast(ctype, parse_unary())

        return parse_postfix()

    def parse_postfix() -> AST.Expr:
        expr = parse_primary()
        while True:
            if match(TokenKind.LPAREN):
                args: list[AST.Expr] = []
                if not at(TokenKind.RPAREN):
                    while True:
                        args.append(parse_assign_expr())
                        if not match(TokenKind.COMMA):
                            break
                expect(TokenKind.RPAREN)
                expr = AST.Call(expr, args)
                continue
            if match(TokenKind.LBRACKET):
                index = parse_expr()
                expect(TokenKind.RBRACKET)
                expr = AST.ArraySubscript(expr, index)
                continue
            if match(TokenKind.DOT):
                expr = AST.Member(expr, expect_ident(), False)
                continue
            if match(TokenKind.ARROW):
                expr = AST.Member(expr, expect_ident(), True)
                continue
            if match(TokenKind.PLUS_PLUS):
                expr = AST.IncDec("++", expr, True)
                continue
            if match(TokenKind.MINUS_MINUS):
                expr = AST.IncDec("--", expr, True)
                continue
            break
        return expr

    def parse_primary() -> AST.Expr:
        tok = peek()
        if tok.kind == TokenKind.INT_LITERAL:
            advance()
            value = tok.value
            assert isinstance(value, int)
            return AST.IntLiteral(value)
        if tok.kind == TokenKind.FLOAT_LITERAL:
            advance()
            value = tok.value
            assert isinstance(value, float)
            return AST.FloatLiteral(value)
        if tok.kind == TokenKind.CHAR_LITERAL:
            advance()
            value = tok.value
            assert isinstance(value, str)
            return AST.CharLiteral(value)
        if tok.kind == TokenKind.STRING_LITERAL:
            advance()
            value = tok.value
            assert isinstance(value, str)
            return AST.StringLiteral(value)
        if tok.kind == TokenKind.IDENT:
            advance()
            value = tok.value
            assert isinstance(value, str)
            return AST.Identifier(value)
        if match(TokenKind.LPAREN):
            expr = parse_expr()
            expect(TokenKind.RPAREN)
            return expr
        error("Expected expression")

    def parse_type_name() -> AST.CType:
        specs = parse_decl_specs(allow_storage=False, allow_function=False)
        declarator = parse_abstract_declarator() if looks_like_abstract_declarator() else None
        return build_type(specs, declarator)

    def build_type(specs: list[AST.DeclSpec], declarator: AST.Declarator | AST.AbstractDeclarator | None) -> AST.CType:
        base = base_type(specs)
        if declarator is None:
            return base
        mods = collect_mods(declarator)
        for mod in reversed(mods):
            if isinstance(mod, AST.Pointer):
                base = AST.PointerType(base)
            elif mod.array_size is not None or mod.params is None:
                base = AST.ArrayType(base, mod.array_size)
            else:
                params = build_params(mod.params)
                base = AST.FunctionType(base, params, mod.is_variadic)
        return base

    def build_params(params: list[AST.ParamDecl]) -> list[AST.Param]:
        items: list[AST.Param] = []
        for param in params:
            if param.declarator is None:
                name = ""
                ctype = build_type(param.specs, None)
            elif isinstance(param.declarator, AST.Declarator):
                name = declarator_name(param.declarator)
                ctype = build_type(param.specs, param.declarator)
            else:
                name = ""
                ctype = build_type(param.specs, param.declarator)
            items.append(AST.Param(name, ctype))
        return items

    def base_type(specs: list[AST.DeclSpec]) -> AST.CType:
        for spec in specs:
            if isinstance(spec, AST.TypeSpec):
                return spec.ctype
        error("Missing type specifier")

    def collect_mods(decl: AST.Declarator | AST.AbstractDeclarator) -> list[AST.Pointer | AST.DirectSuffix]:
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

    def declarator_name(decl: AST.Declarator) -> str:
        direct = decl.direct
        while direct is not None:
            if direct.name is not None:
                return direct.name
            if direct.nested is None:
                break
            decl = direct.nested
            direct = decl.direct
        error("Expected declarator name")

    def extract_tag_def(specs: list[AST.DeclSpec]) -> AST.StructDef | AST.UnionDef | AST.EnumDef | None:
        for spec in specs:
            if isinstance(spec, AST.TypeSpec):
                if isinstance(spec.ctype, AST.StructType) and spec.ctype.fields is not None:
                    return AST.StructDef(spec.ctype.name, spec.ctype.fields)
                if isinstance(spec.ctype, AST.UnionType) and spec.ctype.fields is not None:
                    return AST.UnionDef(spec.ctype.name, spec.ctype.fields)
                if isinstance(spec.ctype, AST.EnumType) and spec.ctype.values is not None:
                    return AST.EnumDef(spec.ctype.name, spec.ctype.values)
        return None

    return parse_program()
