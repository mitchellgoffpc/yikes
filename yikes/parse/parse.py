from __future__ import annotations

from typing import NoReturn

from yikes.lex.lex import Token, lex
from yikes.lex.tokens import ASSIGN_OPS, BUILTIN_TYPES, FUNC_SPEC, KEYWORDS_BY_KIND, PUNCTUATORS_BY_KIND, STORAGE_CLASS, TYPE_QUAL, TokenKind
from yikes.parse import ast as AST  # noqa: N812


def parse(source: str, *, with_spans: bool = True) -> AST.Program:
    tokens = lex(source)
    pos = 0
    typedef_names: set[str] = set()

    def ident(tok: Token) -> AST.Identifier:
        assert tok.kind == TokenKind.IDENT
        assert isinstance(tok.value, str)
        return AST.Identifier(tok.value, span(tok))

    def span(tok: Token) -> AST.Span | None:
        if not with_spans:
            return None
        return AST.Span(AST.Position(tok.line, tok.col), AST.Position(tok.line, tok.col + tok.length))

    def span_from(start_pos: int) -> AST.Span | None:
        if not with_spans:
            return None
        if pos <= start_pos:
            return span(tokens[start_pos])
        start, end = tokens[start_pos], tokens[pos - 1]
        return AST.Span(AST.Position(start.line, start.col), AST.Position(end.line, end.col + end.length))

    def merge_spans(left: AST.Span | None, right: AST.Span | None) -> AST.Span | None:
        if not with_spans or left is None or right is None:
            return None
        return AST.Span(left.start, right.end)

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

    def match_ident() -> AST.Identifier | None:
        if at(TokenKind.IDENT):
            return ident(advance())
        return None

    def expect_ident() -> AST.Identifier:
        if not at(TokenKind.IDENT):
            error("Expected identifier")
        return ident(advance())

    def error(message: str) -> NoReturn:
        tok = peek()
        raise ValueError(f"{message} at {tok.line}:{tok.col}")

    def is_decl_start(tok: Token) -> bool:
        return (
            tok.kind in STORAGE_CLASS
            or tok.kind in TYPE_QUAL
            or tok.kind in FUNC_SPEC
            or tok.kind in BUILTIN_TYPES
            or tok.kind in {TokenKind.KW_STRUCT, TokenKind.KW_UNION, TokenKind.KW_ENUM}
            or (tok.kind == TokenKind.IDENT and tok.value in typedef_names)
        )

    def looks_like_type_name() -> bool:
        if at(TokenKind.LPAREN):
            return pos + 1 < len(tokens) and is_decl_start(tokens[pos + 1])
        return is_decl_start(peek())

    def looks_like_abstract_declarator() -> bool:
        return peek().kind in {TokenKind.STAR, TokenKind.LPAREN, TokenKind.LBRACKET}

    def looks_like_named_declarator() -> bool:
        for tok in tokens[pos:]:
            if tok.kind == TokenKind.IDENT:
                return True
            if tok.kind in {TokenKind.COMMA, TokenKind.RPAREN, TokenKind.RBRACKET, TokenKind.SEMI}:
                return False
        return False

    def has_storage(specs: list[AST.DeclSpec], name: str) -> bool:
        return any(isinstance(s, AST.StorageClassSpec) and s.name == name for s in specs)

    def is_void_param(specs: list[AST.DeclSpec], decl: AST.Declarator | AST.AbstractDeclarator | None, params: list[AST.ParamDecl]) -> bool:
        if decl is not None or params:
            return False
        match specs:
            case [AST.BuiltinType(keywords=[AST.TypeKeyword(name="void")])]:
                return True
        return False

    def parse_program() -> AST.Program:
        start_pos = pos
        items: list[AST.ExternalDecl] = []
        while not at(TokenKind.EOF):
            items.append(parse_external_decl())
        return AST.Program(items, scope=AST.Scope(), span=span_from(start_pos))

    def parse_external_decl() -> AST.ExternalDecl:
        start_pos = pos
        specs = parse_decl_specs()
        if match(TokenKind.SEMI):
            return extract_tag_def(specs) or AST.Declaration(specs, [], span=span_from(start_pos))

        decls = parse_init_declarator_list()
        if at(TokenKind.LBRACE):
            if len(decls) != 1 or decls[0].init is not None:
                error("Invalid function definition")
            name = declarator_name(decls[0].declarator)
            ctype = build_type(specs, decls[0].declarator)
            if not isinstance(ctype, AST.FunctionType):
                error("Function definition requires function type")
            else:
                body = parse_block()
                return AST.FunctionDef(name, ctype.params, ctype.return_type, ctype.variadic, body, scope=AST.Scope(), span=span_from(start_pos))

        expect(TokenKind.SEMI)
        if has_storage(specs, "typedef"):
            if len(decls) == 1 and decls[0].init is None:
                name = declarator_name(decls[0].declarator)
                ctype = build_type(specs, decls[0].declarator)
                typedef_names.add(name.name)
                return AST.TypeDef(name, ctype, span=span_from(start_pos))
            return AST.Declaration(specs, decls, span=span_from(start_pos))

        if len(decls) == 1:
            name = declarator_name(decls[0].declarator)
            ctype = build_type(specs, decls[0].declarator)
            return AST.VarDecl(name, ctype, decls[0].init, span=span_from(start_pos))
        return AST.Declaration(specs, decls, span=span_from(start_pos))

    def parse_block() -> AST.Block:
        start_pos = pos
        expect(TokenKind.LBRACE)
        items: list[AST.Stmt] = []
        while not at(TokenKind.RBRACE):
            if at(TokenKind.KW_CASE):
                items.append(parse_case())
            elif at(TokenKind.KW_DEFAULT):
                items.append(parse_default())
            elif is_decl_start(peek()):
                items.append(parse_declaration())
            else:
                items.append(parse_stmt())
        expect(TokenKind.RBRACE)
        return AST.Block(items, scope=AST.Scope(), span=span_from(start_pos))

    def parse_stmt() -> AST.Stmt:
        start_pos = pos
        if at(TokenKind.LBRACE):
            return parse_block()
        if match(TokenKind.KW_RETURN):
            value = None if at(TokenKind.SEMI) else parse_expr()
            expect(TokenKind.SEMI)
            return AST.Return(value, span=span_from(start_pos))
        if match(TokenKind.KW_IF):
            expect(TokenKind.LPAREN)
            cond = parse_expr()
            expect(TokenKind.RPAREN)
            then = parse_stmt()
            otherwise = parse_stmt() if match(TokenKind.KW_ELSE) else None
            return AST.If(cond, then, otherwise, span=span_from(start_pos))
        if match(TokenKind.KW_WHILE):
            expect(TokenKind.LPAREN)
            cond = parse_expr()
            expect(TokenKind.RPAREN)
            return AST.While(cond, parse_stmt(), span=span_from(start_pos))
        if match(TokenKind.KW_DO):
            body = parse_stmt()
            expect(TokenKind.KW_WHILE)
            expect(TokenKind.LPAREN)
            cond = parse_expr()
            expect(TokenKind.RPAREN)
            expect(TokenKind.SEMI)
            return AST.DoWhile(body, cond, span=span_from(start_pos))
        if match(TokenKind.KW_FOR):
            return parse_for(start_pos)
        if match(TokenKind.KW_BREAK):
            expect(TokenKind.SEMI)
            return AST.Break(span=span_from(start_pos))
        if match(TokenKind.KW_CONTINUE):
            expect(TokenKind.SEMI)
            return AST.Continue(span=span_from(start_pos))
        if match(TokenKind.KW_SWITCH):
            expect(TokenKind.LPAREN)
            expr = parse_expr()
            expect(TokenKind.RPAREN)
            body = parse_block()
            return AST.Switch(expr, body, span=span_from(start_pos))
        if match(TokenKind.KW_GOTO):
            target = expect_ident()
            expect(TokenKind.SEMI)
            return AST.Goto(target, span=span_from(start_pos))
        if at(TokenKind.IDENT) and peek(1).kind == TokenKind.COLON:
            name = expect_ident()
            expect(TokenKind.COLON)
            return AST.Label(name, parse_stmt(), span=span_from(start_pos))

        expr = None if at(TokenKind.SEMI) else parse_expr()
        expect(TokenKind.SEMI)
        return AST.ExprStmt(expr, span=span_from(start_pos))

    def parse_case() -> AST.Case:
        start_pos = pos
        expect(TokenKind.KW_CASE)
        value = parse_expr()
        expect(TokenKind.COLON)
        body_items, body_span = parse_stmt_list({TokenKind.KW_CASE, TokenKind.KW_DEFAULT, TokenKind.RBRACE})
        body = AST.Block(body_items, scope=AST.Scope(), span=body_span)
        return AST.Case(value, body, span=span_from(start_pos))

    def parse_default() -> AST.Default:
        start_pos = pos
        expect(TokenKind.KW_DEFAULT)
        expect(TokenKind.COLON)
        body_items, body_span = parse_stmt_list({TokenKind.KW_CASE, TokenKind.KW_DEFAULT, TokenKind.RBRACE})
        body = AST.Block(body_items, scope=AST.Scope(), span=body_span)
        return AST.Default(body, span=span_from(start_pos))

    def parse_stmt_list(stop: set[TokenKind]) -> tuple[list[AST.Stmt], AST.Span | None]:
        start_pos = pos
        items: list[AST.Stmt] = []
        while not at_any(stop):
            if is_decl_start(peek()):
                items.append(parse_declaration())
            else:
                items.append(parse_stmt())
        return items, span_from(start_pos) if items else None

    def parse_for(start_pos: int) -> AST.For:
        expect(TokenKind.LPAREN)
        if match(TokenKind.SEMI):
            init = None
        elif is_decl_start(peek()):
            init = parse_declaration()
        else:
            init_start_pos = pos
            init_expr = parse_expr()
            expect(TokenKind.SEMI)
            init = AST.ExprStmt(init_expr, span=span_from(init_start_pos))

        if match(TokenKind.SEMI):
            cond = None
        else:
            cond = parse_expr()
            expect(TokenKind.SEMI)

        step = None if at(TokenKind.RPAREN) else parse_expr()
        expect(TokenKind.RPAREN)
        return AST.For(init, cond, step, parse_stmt(), scope=AST.Scope(), span=span_from(start_pos))

    def parse_declaration() -> AST.Stmt:
        start_pos = pos
        specs = parse_decl_specs()
        if match(TokenKind.SEMI):
            return extract_tag_def(specs) or AST.Declaration(specs, [], span=span_from(start_pos))
        decls = parse_init_declarator_list()
        expect(TokenKind.SEMI)

        if has_storage(specs, "typedef"):
            if len(decls) == 1 and decls[0].init is None:
                name = declarator_name(decls[0].declarator)
                ctype = build_type(specs, decls[0].declarator)
                typedef_names.add(name.name)
                return AST.TypeDef(name, ctype, span=span_from(start_pos))
            return AST.Declaration(specs, decls, span=span_from(start_pos))

        if len(decls) == 1:
            name = declarator_name(decls[0].declarator)
            ctype = build_type(specs, decls[0].declarator)
            return AST.VarDecl(name, ctype, decls[0].init, span=span_from(start_pos))
        return AST.Declaration(specs, decls, span=span_from(start_pos))

    def parse_decl_specs(allow_storage: bool = True, allow_function: bool = True) -> list[AST.DeclSpec]:
        specs: list[AST.DeclSpec] = []
        builtins: list[AST.TypeKeyword] = []
        seen_type_spec = False

        while True:
            tok = peek()
            if tok.kind in STORAGE_CLASS:
                if not allow_storage:
                    error("Storage class not allowed here")
                specs.append(AST.StorageClassSpec(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
                advance()
            elif tok.kind in TYPE_QUAL:
                specs.append(AST.TypeQualifier(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
                advance()
            elif tok.kind in FUNC_SPEC:
                if not allow_function:
                    error("Function specifier not allowed here")
                specs.append(AST.FunctionSpec(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
                advance()
            elif tok.kind in BUILTIN_TYPES:
                builtins.append(AST.TypeKeyword(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
                advance()
            elif tok.kind == TokenKind.KW_STRUCT:
                specs.append(parse_struct_type())
                seen_type_spec = True
            elif tok.kind == TokenKind.KW_UNION:
                specs.append(parse_union_type())
                seen_type_spec = True
            elif tok.kind == TokenKind.KW_ENUM:
                specs.append(parse_enum_type())
                seen_type_spec = True
            elif tok.kind == TokenKind.IDENT and tok.value in typedef_names:
                name = ident(advance())
                specs.append(AST.NamedType(name, span=name.span))
                seen_type_spec = True
            else:
                break

        if builtins:
            if seen_type_spec:
                error("Multiple type specifiers")
            builtins_span = merge_spans(builtins[0].span, builtins[-1].span)
            specs.append(AST.BuiltinType(builtins, span=builtins_span))
            seen_type_spec = True

        if not seen_type_spec:
            error("Expected type specifier")
        return specs

    def parse_struct_type() -> AST.StructType:
        start_pos = pos
        expect(TokenKind.KW_STRUCT)
        name = match_ident()
        if match(TokenKind.LBRACE):
            fields = parse_struct_fields()
            expect(TokenKind.RBRACE)
            return AST.StructType(name, fields, span=span_from(start_pos))
        return AST.StructType(name, None, span=span_from(start_pos))

    def parse_union_type() -> AST.UnionType:
        start_pos = pos
        expect(TokenKind.KW_UNION)
        name = match_ident()
        if match(TokenKind.LBRACE):
            fields = parse_struct_fields()
            expect(TokenKind.RBRACE)
            return AST.UnionType(name, fields, span=span_from(start_pos))
        return AST.UnionType(name, None, span=span_from(start_pos))

    def parse_enum_type() -> AST.EnumType:
        start_pos = pos
        expect(TokenKind.KW_ENUM)
        name = match_ident()
        if match(TokenKind.LBRACE):
            values: list[AST.Enumerator] = []
            while not at(TokenKind.RBRACE):
                enum_start_pos = pos
                enum_name = expect_ident()
                value = parse_expr() if match(TokenKind.ASSIGN) else None
                values.append(AST.Enumerator(enum_name, value, span=span_from(enum_start_pos)))
                if not match(TokenKind.COMMA):
                    break
            expect(TokenKind.RBRACE)
            return AST.EnumType(name, values, span=span_from(start_pos))
        return AST.EnumType(name, None, span=span_from(start_pos))

    def parse_struct_fields() -> list[AST.Field]:
        fields: list[AST.Field] = []
        while not at(TokenKind.RBRACE):
            spec_start_pos = pos
            specs = parse_decl_specs(allow_storage=False, allow_function=False)
            if match(TokenKind.SEMI):
                continue
            while True:
                field_start_pos = spec_start_pos
                if match(TokenKind.COLON):
                    bit_width = parse_expr()
                    ctype = build_type(specs, None)
                    fields.append(AST.Field(None, ctype, bit_width, span=span_from(field_start_pos)))
                else:
                    decl = parse_declarator()
                    bit_width = parse_expr() if match(TokenKind.COLON) else None
                    name = declarator_name(decl)
                    ctype = build_type(specs, decl)
                    fields.append(AST.Field(name, ctype, bit_width, span=span_from(field_start_pos)))
                if not match(TokenKind.COMMA):
                    break
            expect(TokenKind.SEMI)
        return fields

    def parse_init_declarator_list() -> list[AST.InitDeclarator]:
        items: list[AST.InitDeclarator] = []
        while True:
            start_pos = pos
            decl = parse_declarator()
            init = parse_initializer() if match(TokenKind.ASSIGN) else None
            items.append(AST.InitDeclarator(decl, init, span=span_from(start_pos)))
            if not match(TokenKind.COMMA):
                break
        return items

    def parse_direct_suffixes() -> list[AST.DirectSuffix]:
        suffixes: list[AST.DirectSuffix] = []
        while True:
            if match(TokenKind.LPAREN):
                suffix_start_pos = pos - 1
                params, is_variadic = parse_param_list()
                expect(TokenKind.RPAREN)
                suffixes.append(AST.DirectSuffix(params, None, False, is_variadic, span=span_from(suffix_start_pos)))
            elif match(TokenKind.LBRACKET):
                suffix_start_pos = pos - 1
                is_static = match(TokenKind.KW_STATIC)
                size = None if at(TokenKind.RBRACKET) else parse_expr()
                expect(TokenKind.RBRACKET)
                suffixes.append(AST.DirectSuffix(None, size, is_static, False, span=span_from(suffix_start_pos)))
            else:
                break
        return suffixes

    def parse_declarator() -> AST.Declarator:
        start_pos = pos
        pointer = parse_pointer()
        direct = parse_direct_declarator()
        return AST.Declarator(pointer, direct, span=span_from(start_pos))

    def parse_direct_declarator() -> AST.DirectDeclarator:
        start_pos = pos
        name: AST.Identifier | None = None
        nested: AST.Declarator | None = None
        if at(TokenKind.IDENT):
            name = expect_ident()
        elif match(TokenKind.LPAREN):
            nested = parse_declarator()
            expect(TokenKind.RPAREN)
        else:
            error("Expected declarator")

        suffixes = parse_direct_suffixes()
        return AST.DirectDeclarator(name, nested, suffixes, span=span_from(start_pos))

    def parse_abstract_declarator() -> AST.AbstractDeclarator:
        start_pos = pos
        pointer = parse_pointer()
        direct = parse_direct_abstract_declarator()
        return AST.AbstractDeclarator(pointer, direct, span=span_from(start_pos))

    def parse_direct_abstract_declarator() -> AST.DirectAbstractDeclarator | None:
        start_pos = pos
        nested: AST.AbstractDeclarator | None = None
        if match(TokenKind.LPAREN):
            if not at(TokenKind.RPAREN):
                nested = parse_abstract_declarator()
            expect(TokenKind.RPAREN)

        suffixes = parse_direct_suffixes()
        return AST.DirectAbstractDeclarator(nested, suffixes, span=span_from(start_pos)) if nested or suffixes else None

    def parse_pointer() -> AST.Pointer | None:
        if not match(TokenKind.STAR):
            return None
        start_pos = pos - 1
        qualifiers: list[AST.TypeQualifier] = []
        while peek().kind in TYPE_QUAL:
            qualifiers.append(AST.TypeQualifier(KEYWORDS_BY_KIND[peek().kind], span=span(peek())))
            advance()
        return AST.Pointer(qualifiers, parse_pointer(), span=span_from(start_pos))

    def parse_param_list() -> tuple[list[AST.ParamDecl], bool]:
        if at(TokenKind.RPAREN):
            return [], False

        params: list[AST.ParamDecl] = []
        is_variadic = False
        while True:
            if match(TokenKind.ELLIPSIS):
                is_variadic = True
                break
            start_pos = pos
            specs = parse_decl_specs(allow_storage=False, allow_function=False)
            decl = None
            if not at_any({TokenKind.COMMA, TokenKind.RPAREN}):
                decl = parse_declarator() if looks_like_named_declarator() else parse_abstract_declarator()
            if is_void_param(specs, decl, params):
                params = []
                break
            params.append(AST.ParamDecl(specs, decl, span=span_from(start_pos)))
            if match(TokenKind.COMMA):
                continue
            break
        return params, is_variadic

    def parse_initializer() -> AST.Initializer:
        if not at(TokenKind.LBRACE):
            return parse_assign_expr()
        start_pos = pos
        expect(TokenKind.LBRACE)
        items: list[AST.InitializerItem] = []
        while not at(TokenKind.RBRACE):
            item_start_pos = pos
            designators = parse_designators()
            if designators and match(TokenKind.ASSIGN):
                pass
            value = parse_initializer()
            items.append(AST.InitializerItem(designators, value, span=span_from(item_start_pos)))
            if not match(TokenKind.COMMA):
                break
        expect(TokenKind.RBRACE)
        return AST.InitList(items, span=span_from(start_pos))

    def parse_designators() -> list[AST.Designator]:
        items: list[AST.Designator] = []
        while True:
            if match(TokenKind.DOT):
                start_pos = pos - 1
                items.append(AST.Designator(expect_ident(), None, span=span_from(start_pos)))
            elif match(TokenKind.LBRACKET):
                start_pos = pos - 1
                index = parse_expr()
                expect(TokenKind.RBRACKET)
                items.append(AST.Designator(None, index, span=span_from(start_pos)))
            else:
                break
        return items

    def parse_expr() -> AST.Expr:
        start_pos = pos
        expr = parse_assign_expr()
        while match(TokenKind.COMMA):
            expr = AST.Binary(",", expr, parse_assign_expr(), span=span_from(start_pos))
        return expr

    def parse_assign_expr() -> AST.Expr:
        start_pos = pos
        expr = parse_conditional_expr()
        if peek().kind in ASSIGN_OPS:
            op = advance().kind
            value = parse_assign_expr()
            if op == TokenKind.ASSIGN:
                return AST.Assign(expr, value, span=span_from(start_pos))
            binary = AST.Binary(PUNCTUATORS_BY_KIND[op][:-1], expr, value, span=merge_spans(expr.span, value.span))
            return AST.Assign(expr, binary, span=span_from(start_pos))
        return expr

    def parse_conditional_expr() -> AST.Expr:
        start_pos = pos
        expr = parse_logical_or()
        if match(TokenKind.QUESTION):
            then = parse_expr()
            expect(TokenKind.COLON)
            otherwise = parse_conditional_expr()
            return AST.Conditional(expr, then, otherwise, span=span_from(start_pos))
        return expr

    def parse_logical_or() -> AST.Expr:
        start_pos = pos
        expr = parse_logical_and()
        while match(TokenKind.OR_OR):
            expr = AST.Binary("||", expr, parse_logical_and(), span=span_from(start_pos))
        return expr

    def parse_logical_and() -> AST.Expr:
        start_pos = pos
        expr = parse_bitwise_or()
        while match(TokenKind.AND_AND):
            expr = AST.Binary("&&", expr, parse_bitwise_or(), span=span_from(start_pos))
        return expr

    def parse_bitwise_or() -> AST.Expr:
        start_pos = pos
        expr = parse_bitwise_xor()
        while match(TokenKind.PIPE):
            expr = AST.Binary("|", expr, parse_bitwise_xor(), span=span_from(start_pos))
        return expr

    def parse_bitwise_xor() -> AST.Expr:
        start_pos = pos
        expr = parse_bitwise_and()
        while match(TokenKind.CARET):
            expr = AST.Binary("^", expr, parse_bitwise_and(), span=span_from(start_pos))
        return expr

    def parse_bitwise_and() -> AST.Expr:
        start_pos = pos
        expr = parse_equality()
        while match(TokenKind.AMP):
            expr = AST.Binary("&", expr, parse_equality(), span=span_from(start_pos))
        return expr

    def parse_equality() -> AST.Expr:
        start_pos = pos
        expr = parse_relational()
        while True:
            if match(TokenKind.EQ):
                expr = AST.Binary("==", expr, parse_relational(), span=span_from(start_pos))
            elif match(TokenKind.NE):
                expr = AST.Binary("!=", expr, parse_relational(), span=span_from(start_pos))
            else:
                break
        return expr

    def parse_relational() -> AST.Expr:
        start_pos = pos
        expr = parse_shift()
        while True:
            if match(TokenKind.LT):
                expr = AST.Binary("<", expr, parse_shift(), span=span_from(start_pos))
            elif match(TokenKind.GT):
                expr = AST.Binary(">", expr, parse_shift(), span=span_from(start_pos))
            elif match(TokenKind.LE):
                expr = AST.Binary("<=", expr, parse_shift(), span=span_from(start_pos))
            elif match(TokenKind.GE):
                expr = AST.Binary(">=", expr, parse_shift(), span=span_from(start_pos))
            else:
                break
        return expr

    def parse_shift() -> AST.Expr:
        start_pos = pos
        expr = parse_additive()
        while True:
            if match(TokenKind.LSHIFT):
                expr = AST.Binary("<<", expr, parse_additive(), span=span_from(start_pos))
            elif match(TokenKind.RSHIFT):
                expr = AST.Binary(">>", expr, parse_additive(), span=span_from(start_pos))
            else:
                break
        return expr

    def parse_additive() -> AST.Expr:
        start_pos = pos
        expr = parse_multiplicative()
        while True:
            if match(TokenKind.PLUS):
                expr = AST.Binary("+", expr, parse_multiplicative(), span=span_from(start_pos))
            elif match(TokenKind.MINUS):
                expr = AST.Binary("-", expr, parse_multiplicative(), span=span_from(start_pos))
            else:
                break
        return expr

    def parse_multiplicative() -> AST.Expr:
        start_pos = pos
        expr = parse_unary()
        while True:
            if match(TokenKind.STAR):
                expr = AST.Binary("*", expr, parse_unary(), span=span_from(start_pos))
            elif match(TokenKind.SLASH):
                expr = AST.Binary("/", expr, parse_unary(), span=span_from(start_pos))
            elif match(TokenKind.PERCENT):
                expr = AST.Binary("%", expr, parse_unary(), span=span_from(start_pos))
            else:
                break
        return expr

    def parse_unary() -> AST.Expr:
        start_pos = pos
        if match(TokenKind.PLUS_PLUS):
            return AST.IncDec("++", parse_unary(), False, span=span_from(start_pos))
        if match(TokenKind.MINUS_MINUS):
            return AST.IncDec("--", parse_unary(), False, span=span_from(start_pos))
        if match(TokenKind.PLUS):
            return AST.Unary("+", parse_unary(), span=span_from(start_pos))
        if match(TokenKind.MINUS):
            return AST.Unary("-", parse_unary(), span=span_from(start_pos))
        if match(TokenKind.BANG):
            return AST.Unary("!", parse_unary(), span=span_from(start_pos))
        if match(TokenKind.TILDE):
            return AST.Unary("~", parse_unary(), span=span_from(start_pos))
        if match(TokenKind.STAR):
            return AST.Unary("*", parse_unary(), span=span_from(start_pos))
        if match(TokenKind.AMP):
            return AST.Unary("&", parse_unary(), span=span_from(start_pos))
        if match(TokenKind.KW_SIZEOF):
            sizeof_start_pos = pos - 1
            if match(TokenKind.LPAREN) and looks_like_type_name():
                ctype = parse_type_name()
                expect(TokenKind.RPAREN)
                return AST.Sizeof(ctype, span=span_from(sizeof_start_pos))
            if peek(-1).kind == TokenKind.LPAREN:
                error("Expected type name")
            return AST.Sizeof(parse_unary(), span=span_from(sizeof_start_pos))

        if at(TokenKind.LPAREN) and looks_like_type_name():
            cast_start_pos = pos
            expect(TokenKind.LPAREN)
            ctype = parse_type_name()
            expect(TokenKind.RPAREN)
            if at(TokenKind.LBRACE):
                init = parse_initializer()
                return AST.CompoundLiteral(ctype, init, span=span_from(cast_start_pos))
            return AST.Cast(ctype, parse_unary(), span=span_from(cast_start_pos))

        return parse_postfix()

    def parse_postfix() -> AST.Expr:
        start_pos = pos
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
                expr = AST.Call(expr, args, span=span_from(start_pos))
            elif match(TokenKind.LBRACKET):
                index = parse_expr()
                expect(TokenKind.RBRACKET)
                expr = AST.ArraySubscript(expr, index, span=span_from(start_pos))
            elif match(TokenKind.DOT):
                expr = AST.Member(expr, expect_ident(), False, span=span_from(start_pos))
            elif match(TokenKind.ARROW):
                expr = AST.Member(expr, expect_ident(), True, span=span_from(start_pos))
            elif match(TokenKind.PLUS_PLUS):
                expr = AST.IncDec("++", expr, True, span=span_from(start_pos))
            elif match(TokenKind.MINUS_MINUS):
                expr = AST.IncDec("--", expr, True, span=span_from(start_pos))
            else:
                break
        return expr

    def parse_primary() -> AST.Expr:
        tok = peek()
        if match(TokenKind.INT_LITERAL):
            assert isinstance(tok.value, int)
            return AST.IntLiteral(tok.value, span=span(tok))
        if match(TokenKind.FLOAT_LITERAL):
            assert isinstance(tok.value, float)
            return AST.FloatLiteral(tok.value, span=span(tok))
        if match(TokenKind.CHAR_LITERAL):
            assert isinstance(tok.value, str)
            return AST.CharLiteral(tok.value, span=span(tok))
        if match(TokenKind.STRING_LITERAL):
            assert isinstance(tok.value, str)
            return AST.StringLiteral(tok.value, span=span(tok))
        if match(TokenKind.IDENT):
            return ident(tok)
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
            match mod:
                case AST.Pointer():
                    base = AST.PointerType(base, span=merge_spans(mod.span, base.span))
                case AST.DirectSuffix(array_size=None, params=[*params], is_variadic=is_variadic):
                    base = AST.FunctionType(base, [build_param(param) for param in params], is_variadic, span=merge_spans(mod.span, base.span))
                case AST.DirectSuffix(array_size=array_size):
                    base = AST.ArrayType(base, array_size, span=merge_spans(mod.span, base.span))
        return base

    def build_param(param: AST.ParamDecl) -> AST.Param:
        match param.declarator:
            case None:
                return AST.Param(None, build_type(param.specs, None), span=param.span)
            case AST.Declarator() as decl:
                return AST.Param(declarator_name(decl), build_type(param.specs, decl), span=param.span)
            case AST.AbstractDeclarator() as decl:
                return AST.Param(None, build_type(param.specs, decl), span=param.span)

    def base_type(specs: list[AST.DeclSpec]) -> AST.CType:
        for spec in specs:
            if isinstance(spec, AST.CType):
                return spec
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

        match decl:
            case AST.Declarator():
                walk_decl(decl)
            case AST.AbstractDeclarator():
                walk_abstract(decl)
        return mods

    def declarator_name(decl: AST.Declarator) -> AST.Identifier:
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
            match spec:
                case AST.StructType(fields=[*fields], name=name, span=span):
                    return AST.StructDef(name, fields, span=span)
                case AST.UnionType(fields=[*fields], name=name, span=span):
                    return AST.UnionDef(name, fields, span=span)
                case AST.EnumType(values=[*values], name=name, span=span):
                    return AST.EnumDef(name, values, span=span)
        return None

    return parse_program()
