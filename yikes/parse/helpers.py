from __future__ import annotations

from yikes.parse import ast as AST  # noqa: N812


def const_eval(expr: AST.Expr | None) -> int | None:
    if expr is None:
        return None
    match expr:
        case AST.IntLiteral(value=value):
            return value
        case AST.CharLiteral(value=value):
            return ord(value) if value else 0
        case AST.BoolLiteral(value=value):
            return 1 if value else 0
        case AST.Unary(op=op, value=value):
            inner = const_eval(value)
            if inner is None:
                return None
            if op == "+":
                return inner
            if op == "-":
                return -inner
            if op == "~":
                return ~inner
            if op == "!":
                return 0 if inner else 1
        case AST.Binary(op=op, left=left, right=right):
            left_val = const_eval(left)
            right_val = const_eval(right)
            if left_val is None or right_val is None:
                return None
            match op:
                case "+":
                    return left_val + right_val
                case "-":
                    return left_val - right_val
                case "*":
                    return left_val * right_val
                case "/":
                    return int(left_val / right_val) if right_val != 0 else None
                case "%":
                    return left_val % right_val if right_val != 0 else None
                case "<<":
                    return left_val << right_val
                case ">>":
                    return left_val >> right_val
                case "&":
                    return left_val & right_val
                case "|":
                    return left_val | right_val
                case "^":
                    return left_val ^ right_val
                case "==":
                    return 1 if left_val == right_val else 0
                case "!=":
                    return 1 if left_val != right_val else 0
                case "<":
                    return 1 if left_val < right_val else 0
                case "<=":
                    return 1 if left_val <= right_val else 0
                case ">":
                    return 1 if left_val > right_val else 0
                case ">=":
                    return 1 if left_val >= right_val else 0
        case AST.Conditional(cond=cond, then=then, otherwise=otherwise):
            cond_val = const_eval(cond)
            if cond_val is None:
                return None
            return const_eval(then if cond_val else otherwise)
    return None
