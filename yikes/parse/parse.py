from __future__ import annotations

from typing import NoReturn

from yikes.lex.lex import Token, lex
from yikes.lex.tokens import ASSIGN_OPS, BUILTIN_TYPES, FUNC_SPEC, KEYWORDS_BY_KIND, PUNCTUATORS_BY_KIND, STORAGE_CLASS, TYPE_QUAL, TokenKind
from yikes.parse import ast as AST  # noqa: N812

DECL_START_KINDS = {*STORAGE_CLASS, *TYPE_QUAL, *FUNC_SPEC, *BUILTIN_TYPES, TokenKind.KW_VOID, TokenKind.KW_STRUCT, TokenKind.KW_UNION, TokenKind.KW_ENUM}


def parse(source: str, *, with_spans: bool = True) -> AST.Program:
    tokens = lex(source)
    pos = 0
    typedef_names: set[str] = set()

    def ident(tok: Token) -> AST.Identifier:
        assert tok.kind == TokenKind.IDENT
        assert isinstance(tok.value, str)
        return AST.Identifier(tok.value, span=span(tok))

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
        return AST.Span(left.start, right.end) if left and right else None

    def peek(offset: int = 0) -> Token:
        return tokens[max(0, min(len(tokens) - 1, pos + offset))]

    def at(*kinds: TokenKind) -> bool:
        if not kinds:
            return False
        if len(kinds) == 1:
            return peek().kind == kinds[0]
        return peek().kind in kinds

    def advance() -> Token:
        nonlocal pos
        tok = peek()
        pos = min(pos + 1, len(tokens))
        return tok

    def match(*kinds: TokenKind) -> bool:
        if at(*kinds):
            advance()
            return True
        return False

    def expect(*kinds: TokenKind) -> Token:
        if not at(*kinds):
            if len(kinds) == 1:
                error(f"Expected {kinds[0].value}")
            expected = ", ".join(kind.value for kind in kinds)
            error(f"Expected one of {expected}")
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
        return tok.kind in DECL_START_KINDS or (tok.kind == TokenKind.IDENT and tok.value in typedef_names)

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

    def is_typedef(specs: AST.DeclSpecs) -> bool:
        return any(isinstance(s, AST.StorageClassSpec) and s.name == "typedef" for s in specs.specs)

    def is_void_param(specs: AST.DeclSpecs, decl: AST.Declarator | AST.AbstractDeclarator | None, params: list[AST.ParamDecl]) -> bool:
        if decl or params:
            return False
        match specs:
            case AST.DeclSpecs(ctype=AST.VoidType()):
                return True
        return False

    def parse_program() -> AST.Program:
        start_pos = pos
        items: list[AST.ExternalDecl] = []
        while not at(TokenKind.EOF):
            items.extend(parse_external_decl())
        return AST.Program(items, scope=AST.Scope(), span=span_from(start_pos))

    def ensure_block(stmt: AST.Stmt) -> AST.Block:
        match stmt:
            case AST.Block():
                return stmt
            case _:
                return AST.Block([stmt], scope=AST.Scope(), span=stmt.span)

    def parse_external_decl() -> list[AST.ExternalDecl]:
        start_pos = pos
        specs = parse_decl_specs()
        if match(TokenKind.SEMI):
            tag = extract_tag_def(specs)
            if tag:
                return [tag]
            error("declaration does not declare anything")

        decls = parse_init_declarator_list()
        if at(TokenKind.LBRACE):
            if len(decls) != 1 or decls[0].init:
                error("Invalid function definition")
            name = declarator_name(decls[0].declarator)
            ctype = build_type(specs, decls[0].declarator)
            match ctype:
                case AST.FunctionType():
                    body = parse_block()
                    return [AST.FunctionDef(name, specs, ctype, body, scope=AST.Scope(), span=span_from(start_pos))]
                case _:
                    error("Function definition requires function type")

        expect(TokenKind.SEMI)
        if is_typedef(specs):
            if any(decl.init for decl in decls):
                error("typedef may not have an initializer")
            typedefs: list[AST.ExternalDecl] = []
            for decl in decls:
                name = declarator_name(decl.declarator)
                ctype = build_type(specs, decl.declarator)
                typedef_names.add(name.name)
                typedefs.append(AST.TypeDef(name, ctype, span=span_from(start_pos)))
            return typedefs

        var_decls: list[AST.ExternalDecl] = []
        for decl in decls:
            name = declarator_name(decl.declarator)
            ctype = build_type(specs, decl.declarator)
            var_decls.append(AST.VarDecl(name, ctype, decl.init, span=span_from(start_pos)))
        return var_decls

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
                items.extend(parse_declaration())
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
            then = ensure_block(parse_stmt())
            otherwise = ensure_block(parse_stmt()) if match(TokenKind.KW_ELSE) else None
            return AST.If(cond, then, otherwise, span=span_from(start_pos))
        if match(TokenKind.KW_WHILE):
            expect(TokenKind.LPAREN)
            cond = parse_expr()
            expect(TokenKind.RPAREN)
            return AST.While(cond, ensure_block(parse_stmt()), span=span_from(start_pos))
        if match(TokenKind.KW_DO):
            return parse_do_while(start_pos)
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

    def parse_do_while(start_pos: int) -> AST.While:
        body = parse_stmt()
        expect(TokenKind.KW_WHILE)
        expect(TokenKind.LPAREN)
        cond = parse_expr()
        expect(TokenKind.RPAREN)
        expect(TokenKind.SEMI)
        loop_body = ensure_block(body)
        break_block = AST.Block([AST.Break()], scope=AST.Scope(), span=loop_body.span)
        tail = AST.If(AST.Unary("!", cond, span=cond.span), break_block, None)
        wrapped_body = AST.Block(loop_body.items + [tail], scope=AST.Scope(), span=loop_body.span)
        return AST.While(AST.BoolLiteral(True), wrapped_body, span=span_from(start_pos))

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
        while not at(*stop):
            if is_decl_start(peek()):
                items.extend(parse_declaration())
            else:
                items.append(parse_stmt())
        return items, span_from(start_pos) if items else None

    def parse_for(start_pos: int) -> AST.Stmt:
        expect(TokenKind.LPAREN)
        if match(TokenKind.SEMI):
            init_items: list[AST.Stmt] = []
        elif is_decl_start(peek()):
            init_items = parse_declaration()
        else:
            init_start_pos = pos
            init_expr = parse_expr()
            expect(TokenKind.SEMI)
            init_items = [AST.ExprStmt(init_expr, span=span_from(init_start_pos))]

        if match(TokenKind.SEMI):
            cond = AST.BoolLiteral(True)
        else:
            cond = parse_expr()
            expect(TokenKind.SEMI)

        step_start_pos = pos
        step = None if at(TokenKind.RPAREN) else parse_expr()
        expect(TokenKind.RPAREN)
        loop_body = parse_stmt()

        normalized_body = ensure_block(loop_body)
        if step:
            normalized_body = AST.Block(
                normalized_body.items + [AST.ExprStmt(step, span=span_from(step_start_pos))],
                scope=AST.Scope(),
                span=normalized_body.span,
            )
        loop = AST.While(cond, normalized_body, span=span_from(start_pos))
        if init_items:
            return AST.Block(init_items + [loop], scope=AST.Scope(), span=span_from(start_pos))
        return loop

    def parse_declaration() -> list[AST.Stmt]:
        start_pos = pos
        specs = parse_decl_specs()
        if match(TokenKind.SEMI):
            tag = extract_tag_def(specs)
            if tag:
                return [tag]
            error("declaration does not declare anything")
        decls = parse_init_declarator_list()
        expect(TokenKind.SEMI)

        if is_typedef(specs):
            if any(decl.init for decl in decls):
                error("typedef may not have an initializer")
            typedefs: list[AST.Stmt] = []
            for decl in decls:
                name = declarator_name(decl.declarator)
                ctype = build_type(specs, decl.declarator)
                typedef_names.add(name.name)
                typedefs.append(AST.TypeDef(name, ctype, span=span_from(start_pos)))
            return typedefs

        var_decls: list[AST.Stmt] = []
        for decl in decls:
            name = declarator_name(decl.declarator)
            ctype = build_type(specs, decl.declarator)
            var_decls.append(AST.VarDecl(name, ctype, decl.init, span=span_from(start_pos)))
        return var_decls

    def parse_decl_specs(allow_storage: bool = True, allow_function: bool = True) -> AST.DeclSpecs:
        start_pos = pos
        specs: list[AST.DeclSpec] = []
        types: list[AST.CType] = []
        builtins: list[AST.TypeKeyword] = []
        seen_storage = False

        while True:
            tok = peek()
            if match(*STORAGE_CLASS):
                if not allow_storage:
                    error("Storage class not allowed here")
                if seen_storage:
                    error("Multiple storage class specifiers")
                seen_storage = True
                specs.append(AST.StorageClassSpec(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
            elif match(*TYPE_QUAL):
                specs.append(AST.TypeQualifier(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
            elif match(*FUNC_SPEC):
                if not allow_function:
                    error("Function specifier not allowed here")
                specs.append(AST.FunctionSpec(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
            elif match(TokenKind.KW_VOID):
                types.append(AST.VoidType(span=span(tok)))
            elif match(*BUILTIN_TYPES):
                builtins.append(AST.TypeKeyword(KEYWORDS_BY_KIND[tok.kind], span=span(tok)))
            elif at(TokenKind.KW_STRUCT):
                name, fields, type_span = parse_struct_type()
                types.append(AST.StructType(name, fields, span=type_span))
            elif at(TokenKind.KW_UNION):
                name, fields, type_span = parse_struct_type()
                types.append(AST.UnionType(name, fields, span=type_span))
            elif at(TokenKind.KW_ENUM):
                types.append(parse_enum_type())
            elif at(TokenKind.IDENT) and peek().value in typedef_names:
                name = ident(advance())
                types.append(AST.NamedType(name, span=name.span))
            else:
                break

        if builtins:
            builtins_span = merge_spans(builtins[0].span, builtins[-1].span)
            types.append(AST.BuiltinType(builtins, span=builtins_span))

        if not types:
            error("Expected type specifier")
        if len(types) != 1:
            error("Multiple type specifiers")

        return AST.DeclSpecs(specs, types[0], span=span_from(start_pos))

    def parse_struct_type() -> tuple[AST.Identifier | None, list[AST.Field] | None, AST.Span | None]:
        start_pos = pos
        expect(TokenKind.KW_STRUCT, TokenKind.KW_UNION)
        name = match_ident()
        if match(TokenKind.LBRACE):
            fields = parse_struct_fields()
            expect(TokenKind.RBRACE)
            return name, fields, span_from(start_pos)
        return name, None, span_from(start_pos)

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
            if not at(TokenKind.COMMA, TokenKind.RPAREN):
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
                binary = AST.Binary("+", expr, index, span=merge_spans(expr.span, index.span))
                expr = AST.Unary("*", binary, span=span_from(start_pos))
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

    def build_type(specs: AST.DeclSpecs, declarator: AST.Declarator | AST.AbstractDeclarator | None) -> AST.CType:
        base = specs.ctype
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

    def collect_mods(decl: AST.Declarator | AST.AbstractDeclarator) -> list[AST.Pointer | AST.DirectSuffix]:
        mods: list[AST.Pointer | AST.DirectSuffix] = []

        def walk_decl(d: AST.Declarator) -> None:
            walk_direct(d.direct)
            p = d.pointer
            while p:
                mods.append(p)
                p = p.to

        def walk_direct(d: AST.DirectDeclarator) -> None:
            if d.nested:
                walk_decl(d.nested)
            for suf in d.suffixes:
                mods.append(suf)

        def walk_abstract(d: AST.AbstractDeclarator) -> None:
            if d.direct:
                walk_direct_abs(d.direct)
            p = d.pointer
            while p:
                mods.append(p)
                p = p.to

        def walk_direct_abs(d: AST.DirectAbstractDeclarator) -> None:
            if d.nested:
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
        while direct:
            if direct.name:
                return direct.name
            if direct.nested is None:
                break
            decl = direct.nested
            direct = decl.direct
        error("Expected declarator name")

    def extract_tag_def(specs: AST.DeclSpecs) -> AST.StructDef | AST.UnionDef | AST.EnumDef | None:
        match specs.ctype:
            case AST.StructType(fields=fields, name=name, span=type_span) if fields is not None:
                return AST.StructDef(name, specs.specs, specs.ctype, span=type_span)
            case AST.StructType(fields=None, name=name, span=type_span) if name:
                return AST.StructDef(name, specs.specs, specs.ctype, span=type_span)
            case AST.UnionType(fields=fields, name=name, span=type_span) if fields is not None:
                return AST.UnionDef(name, specs.specs, specs.ctype, span=type_span)
            case AST.UnionType(fields=None, name=name, span=type_span) if name:
                return AST.UnionDef(name, specs.specs, specs.ctype, span=type_span)
            case AST.EnumType(values=values, name=name, span=type_span) if values is not None:
                return AST.EnumDef(name, specs.specs, specs.ctype, span=type_span)
            case AST.EnumType(values=None, name=name, span=type_span) if name:
                return AST.EnumDef(name, specs.specs, specs.ctype, span=type_span)
        return None

    return parse_program()
