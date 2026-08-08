"""Unit tests: safe condition evaluator + conditional branch pruning."""

from __future__ import annotations

import pytest

from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
from nexus.agent.planners.dag_planner import ExecutionTask
from nexus.execution.condition_evaluator import ConditionSyntaxError, evaluate_condition


def test_simple_comparisons():
    acc = {"check": {"count": 7, "status": "premium", "flag": True}}
    assert evaluate_condition("${check.count} > 5", acc) is True
    assert evaluate_condition("${check.count} < 5", acc) is False
    assert evaluate_condition('${check.status} == "premium"', acc) is True
    assert evaluate_condition('${check.status} != "basic"', acc) is True
    assert evaluate_condition("${check.flag} == True", acc) is True


def test_boolean_logic():
    acc = {"a": {"n": 3}, "b": {"n": 9}}
    assert evaluate_condition("${a.n} > 1 and ${b.n} > 5", acc) is True
    assert evaluate_condition("${a.n} > 5 or ${b.n} > 5", acc) is True
    assert evaluate_condition("not ${a.n} > 5", acc) is True


def test_missing_result_is_false():
    assert evaluate_condition("${missing.result.value} > 1", {"other": {}}) is False


def test_unsafe_syntax_rejected():
    with pytest.raises(ConditionSyntaxError):
        evaluate_condition("__import__('os').system('rm -rf /')", {})
    with pytest.raises(ConditionSyntaxError):
        evaluate_condition("getattr(x, 'y')", {"x": {}})


def test_conditional_pruning_true_branch():
    exec_ = ConcurrentExecutor()
    gate = ExecutionTask(
        id="gate", tool_name="__conditional__", kind="conditional",
        condition="${check.count} > 3", branch_true=["t"], branch_false=["f"],
    )
    pruned = exec_._prune_conditional_tasks(
        [gate], {g.id: g for g in [gate]}, {"check": {"count": 9}}
    )
    assert pruned == []
    assert exec_._disabled_task_ids == {"f"}
    assert exec_._conditional_branch["gate"] == ["t"]

    t = ExecutionTask(id="t", tool_name="toolA")
    f = ExecutionTask(id="f", tool_name="toolB")
    assert exec_._is_disabled(t) is False
    assert exec_._is_disabled(f) is True
    assert exec_._is_disabled(ExecutionTask(id="down", tool_name="x", depends_on=["f"])) is True


def test_conditional_pruning_false_branch():
    exec_ = ConcurrentExecutor()
    gate = ExecutionTask(
        id="gate", tool_name="__conditional__", kind="conditional",
        condition="${check.count} > 3", branch_true=["t"], branch_false=["f"],
    )
    exec_._prune_conditional_tasks([gate], {g.id: g for g in [gate]}, {"check": {"count": 1}})
    assert exec_._disabled_task_ids == {"t"}
    assert exec_._conditional_branch["gate"] == ["f"]
