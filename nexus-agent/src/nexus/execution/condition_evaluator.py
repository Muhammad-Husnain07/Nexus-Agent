"""Safe condition evaluator for ConditionalNode execution.

Conditions are user/developer-defined expressions evaluated against the
accumulated execution results — e.g. ``${check.result.count} > 5`` or
``${user.result.status} == "premium"``.

Safety: the expression is parsed with Python's ``ast`` module and only a
whitelisted subset of operations is executed — no attribute access, no
function calls, no imports, no comprehensions. Placeholder values are
resolved from the accumulated results dict before evaluation.

No hardcoded conditions — the grammar is generic and covers comparisons,
boolean logic, arithmetic on numbers, and truthiness.
"""

from __future__ import annotations

import ast
import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\$\{(.+?)(?:\.result)?(?:\.([A-Za-z_][A-Za-z0-9_]*))?\}")

# Placeholder patterns that reference execution results: ${ref.result.field}
_RESULT_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:\.result)?(?:\.([A-Za-z_][A-Za-z0-9_]*))?\}")


class ConditionSyntaxError(ValueError):
    """Raised when a condition expression is syntactically invalid."""


def evaluate_condition(
    condition: str,
    accumulated: dict[str, Any],
    ref_aliases: dict[str, str] | None = None,
) -> bool:
    """Evaluate a condition expression against accumulated results.

    Args:
        condition: Expression like ``${count.result.total} > 5``.
        accumulated: Task-id → result-data map.
        ref_aliases: Optional symbolic-ref → task-id aliases.

    Returns:
        Boolean result of the condition.

    Raises:
        ConditionSyntaxError: If the expression uses unsupported syntax.
    """
    if not condition or not condition.strip():
        return False

    resolved = _resolve_placeholders_in_condition(condition, accumulated, ref_aliases)
    if resolved is None:
        return False

    try:
        tree = ast.parse(resolved, mode="eval")
    except SyntaxError as exc:
        raise ConditionSyntaxError(f"Invalid condition expression: {exc}") from exc

    try:
        value = _eval_node(tree.body)
    except ConditionSyntaxError:
        raise
    except Exception as exc:  # numeric/type errors during eval
        raise ConditionSyntaxError(f"Condition evaluation failed: {exc}") from exc

    return bool(value)


def _resolve_placeholders_in_condition(
    condition: str,
    accumulated: dict[str, Any],
    ref_aliases: dict[str, str] | None,
) -> str | None:
    """Replace result placeholders with JSON-safe literals.

    Returns None when ANY placeholder is unresolvable — a condition over
    missing data conservatively evaluates to False (no branch taken).
    """
    missing = {"found": False}

    def _lookup(task_id: str, field: str | None) -> Any:
        data = accumulated.get(task_id)
        if data is None and ref_aliases:
            physical = ref_aliases.get(task_id)
            if physical and "," not in physical:
                data = accumulated.get(physical)
        if data is None:
            missing["found"] = True
            return None
        if field is None:
            return data
        if isinstance(data, dict):
            return data.get(field)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0].get(field)
        return None

    def _replace(match: re.Match) -> str:
        task_id, field = match.group(1), match.group(2)
        value = _lookup(task_id, field)
        if value is None:
            return "None"
        if isinstance(value, str):
            return repr(value)
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (int, float)):
            return repr(value)
        return repr(str(value))

    resolved = _RESULT_RE.sub(_replace, condition)
    if missing["found"]:
        return None
    return resolved


# Whitelisted AST node evaluator — safe subset only
_BIN_OPS: dict[type, Any] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_CMP_OPS: dict[type, Any] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b,
    ast.IsNot: lambda a, b: a is not b,
}


def _eval_node(node: ast.AST) -> Any:
    """Evaluate a whitelisted AST node. Raises on anything unsupported."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        # Only allow None/True/False literals (they parse as Name in some versions)
        if node.id == "None":
            return None
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        raise ConditionSyntaxError(f"Unknown identifier '{node.id}' in condition")
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ConditionSyntaxError("Unsupported boolean operator")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise ConditionSyntaxError("Unsupported unary operator")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ConditionSyntaxError("Unsupported binary operator")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _CMP_OPS.get(type(op_node))
            if op is None:
                raise ConditionSyntaxError("Unsupported comparison operator")
            right = _eval_node(comparator)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.List):
        return [_eval_node(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(item) for item in node.elts)
    raise ConditionSyntaxError(f"Unsupported syntax: {type(node).__name__}")
