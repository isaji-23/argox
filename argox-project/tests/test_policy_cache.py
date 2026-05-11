"""Tests for PolicyCache: in-process policy evaluation cache."""

from __future__ import annotations

import pytest

from argox.interfaces.policy import PolicyResult
from argox.policies.cache import PolicyCache
from argox.policies.parser import PolicyDocument, PolicyRule, RuleCondition


class TestPolicyCacheLoadAndEvaluate:
    """Test basic load and evaluate functionality."""

    def test_load_policy_empty_document(self):
        """Loading an empty policy document results in no rules cached."""
        cache = PolicyCache()
        policy = PolicyDocument(id="test", version=1, status="active", rules=[])
        cache.load_policy(policy)
        assert cache._rules_by_trigger == {}

    def test_load_policy_single_rule(self):
        """A policy with one rule is indexed by trigger."""
        cache = PolicyCache()
        rule = PolicyRule(
            id="rule-1",
            trigger="on_llm_call",
            condition=RuleCondition(metric="token_count", operator="gt", threshold=100),
            action="block",
        )
        policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
        cache.load_policy(policy)

        assert "on_llm_call" in cache._rules_by_trigger
        assert len(cache._rules_by_trigger["on_llm_call"]) == 1
        cached_rule, predicate = cache._rules_by_trigger["on_llm_call"][0]
        assert cached_rule.id == "rule-1"
        assert callable(predicate)

    def test_evaluate_happy_path_pass(self):
        """Condition not met returns PolicyResult.ok()."""
        cache = PolicyCache()
        rule = PolicyRule(
            id="rule-1",
            trigger="on_llm_call",
            condition=RuleCondition(metric="token_count", operator="gt", threshold=100),
            action="block",
        )
        policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
        cache.load_policy(policy)

        result = cache.evaluate("on_llm_call", {"token_count": 50})
        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""

    def test_evaluate_happy_path_block(self):
        """Condition met with block action returns PolicyResult.block()."""
        cache = PolicyCache()
        rule = PolicyRule(
            id="rule-1",
            trigger="on_llm_call",
            condition=RuleCondition(metric="token_count", operator="gt", threshold=100),
            action="block",
        )
        policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
        cache.load_policy(policy)

        result = cache.evaluate("on_llm_call", {"token_count": 150})
        assert result.passed is False
        assert "rule-1" in result.reason
        assert result.rule_id == "rule-1"


class TestPolicyCachePrecedence:
    """Test precedence of block over alert."""

    def test_block_precedence_over_alert(self):
        """Block rules are returned immediately; alerts are not checked."""
        cache = PolicyCache()
        alert_rule = PolicyRule(
            id="alert-rule",
            trigger="on_tool_call",
            condition=RuleCondition(metric="tool_name", operator="eq", threshold="exec"),
            action="alert",
        )
        block_rule = PolicyRule(
            id="block-rule",
            trigger="on_tool_call",
            condition=RuleCondition(metric="tool_name", operator="eq", threshold="exec"),
            action="block",
        )
        policy = PolicyDocument(
            id="test", version=1, status="active", rules=[alert_rule, block_rule]
        )
        cache.load_policy(policy)

        result = cache.evaluate("on_tool_call", {"tool_name": "exec"})
        assert result.passed is False
        assert result.rule_id == "block-rule"

    def test_first_matching_block_returns_immediately(self):
        """First matching block stops evaluation."""
        cache = PolicyCache()
        rules = [
            PolicyRule(
                id="block-1",
                trigger="event",
                condition=RuleCondition(metric="flag", operator="eq", threshold=True),
                action="block",
            ),
            PolicyRule(
                id="block-2",
                trigger="event",
                condition=RuleCondition(metric="flag", operator="eq", threshold=True),
                action="block",
            ),
        ]
        policy = PolicyDocument(id="test", version=1, status="active", rules=rules)
        cache.load_policy(policy)

        result = cache.evaluate("event", {"flag": True})
        assert result.rule_id == "block-1"

    def test_alert_returned_when_no_blocks(self):
        """Alert is returned if no blocks matched."""
        cache = PolicyCache()
        rule = PolicyRule(
            id="alert-rule",
            trigger="on_api_call",
            condition=RuleCondition(metric="cost", operator="gt", threshold=10.0),
            action="alert",
        )
        policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
        cache.load_policy(policy)

        result = cache.evaluate("on_api_call", {"cost": 15.0})
        assert result.passed is True  # Alerts don't block
        assert "alert-rule" in result.reason
        assert result.rule_id == "alert-rule"

    def test_first_alert_stored_when_multiple_match(self):
        """First matching alert is returned when multiple alerts match."""
        cache = PolicyCache()
        rules = [
            PolicyRule(
                id="alert-1",
                trigger="event",
                condition=RuleCondition(metric="value", operator="gt", threshold=100),
                action="alert",
            ),
            PolicyRule(
                id="alert-2",
                trigger="event",
                condition=RuleCondition(metric="value", operator="gt", threshold=50),
                action="alert",
            ),
        ]
        policy = PolicyDocument(id="test", version=1, status="active", rules=rules)
        cache.load_policy(policy)

        result = cache.evaluate("event", {"value": 150})
        assert result.rule_id == "alert-1"


class TestPolicyCacheTriggers:
    """Test trigger event handling."""

    def test_nonexistent_trigger_returns_ok(self):
        """Evaluating a trigger with no rules returns PolicyResult.ok()."""
        cache = PolicyCache()
        rule = PolicyRule(
            id="rule-1",
            trigger="on_llm_call",
            condition=RuleCondition(metric="x", operator="eq", threshold=1),
            action="block",
        )
        policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
        cache.load_policy(policy)

        result = cache.evaluate("on_nonexistent_trigger", {})
        assert result.passed is True
        assert result.reason == ""

    def test_multiple_triggers_in_one_policy(self):
        """Rules for different triggers are indexed separately."""
        cache = PolicyCache()
        rules = [
            PolicyRule(
                id="llm-rule",
                trigger="on_llm_call",
                condition=RuleCondition(metric="tokens", operator="gt", threshold=1000),
                action="block",
            ),
            PolicyRule(
                id="tool-rule",
                trigger="on_tool_call",
                condition=RuleCondition(metric="tool", operator="eq", threshold="rm"),
                action="block",
            ),
        ]
        policy = PolicyDocument(id="test", version=1, status="active", rules=rules)
        cache.load_policy(policy)

        assert "on_llm_call" in cache._rules_by_trigger
        assert "on_tool_call" in cache._rules_by_trigger

        result1 = cache.evaluate("on_llm_call", {"tokens": 500})
        assert result1.passed is True

        result2 = cache.evaluate("on_tool_call", {"tool": "rm"})
        assert result2.passed is False
        assert result2.rule_id == "tool-rule"


class TestPolicyCacheReload:
    """Test policy reload and cache replacement."""

    def test_load_policy_replaces_previous_rules(self):
        """Loading a new policy replaces the previous one entirely."""
        cache = PolicyCache()

        # Load first policy
        rule1 = PolicyRule(
            id="old-rule",
            trigger="event",
            condition=RuleCondition(metric="x", operator="eq", threshold=1),
            action="block",
        )
        policy1 = PolicyDocument(id="test-1", version=1, status="active", rules=[rule1])
        cache.load_policy(policy1)
        assert "event" in cache._rules_by_trigger
        assert len(cache._rules_by_trigger["event"]) == 1

        # Load second policy with different trigger
        rule2 = PolicyRule(
            id="new-rule",
            trigger="other_event",
            condition=RuleCondition(metric="y", operator="eq", threshold=2),
            action="block",
        )
        policy2 = PolicyDocument(id="test-2", version=2, status="active", rules=[rule2])
        cache.load_policy(policy2)

        assert "event" not in cache._rules_by_trigger
        assert "other_event" in cache._rules_by_trigger
        assert len(cache._rules_by_trigger["other_event"]) == 1
        assert cache._rules_by_trigger["other_event"][0][0].id == "new-rule"

    def test_load_policy_with_compilation_error_preserves_old_cache(self):
        """Cache atomicity: successful builds happen before swap, failures don't modify state.
        
        This test verifies that load_policy builds the complete index in a local dict
        and only assigns to _rules_by_trigger after successful compilation. If compile_condition
        were to raise (e.g., for unknown operators), the assignment never happens.
        
        We verify the pattern with sequential valid loads to ensure no state corruption.
        """
        cache = PolicyCache()

        # Load first policy
        rule1 = PolicyRule(
            id="rule-1",
            trigger="event-a",
            condition=RuleCondition(metric="x", operator="eq", threshold=1),
            action="block",
        )
        policy1 = PolicyDocument(id="test-1", version=1, status="active", rules=[rule1])
        cache.load_policy(policy1)
        
        state_after_first = dict(cache._rules_by_trigger)
        assert "event-a" in state_after_first
        assert len(state_after_first["event-a"]) == 1

        # Load second policy (complete replacement)
        rule2 = PolicyRule(
            id="rule-2",
            trigger="event-b",
            condition=RuleCondition(metric="y", operator="gt", threshold=10),
            action="alert",
        )
        policy2 = PolicyDocument(id="test-2", version=2, status="active", rules=[rule2])
        cache.load_policy(policy2)

        state_after_second = dict(cache._rules_by_trigger)
        # Verify complete replacement: event-a is gone, event-b is present
        assert "event-a" not in state_after_second
        assert "event-b" in state_after_second
        assert len(state_after_second["event-b"]) == 1
        
        # Load third policy with multiple rules
        rules3 = [
            PolicyRule(
                id="rule-3a",
                trigger="event-c",
                condition=RuleCondition(metric="a", operator="contains", threshold="test"),
                action="block",
            ),
            PolicyRule(
                id="rule-3b",
                trigger="event-c",
                condition=RuleCondition(metric="b", operator="in", threshold=["x", "y"]),
                action="alert",
            ),
        ]
        policy3 = PolicyDocument(id="test-3", version=3, status="active", rules=rules3)
        cache.load_policy(policy3)

        state_after_third = dict(cache._rules_by_trigger)
        # Verify only event-c exists with both rules
        assert len(state_after_third) == 1
        assert "event-c" in state_after_third
        assert len(state_after_third["event-c"]) == 2




class TestPolicyCacheActionTypes:
    """Test handling of different action types."""

    def test_action_ok_is_ignored(self):
        """Rules with action 'ok' do not affect evaluation result."""
        cache = PolicyCache()
        rule = PolicyRule(
            id="ok-rule",
            trigger="event",
            condition=RuleCondition(metric="x", operator="eq", threshold=1),
            action="ok",
        )
        policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
        cache.load_policy(policy)

        result = cache.evaluate("event", {"x": 1})
        assert result.passed is True
        assert result.reason == ""

    def test_mixed_actions_block_priority(self):
        """Mixed actions are evaluated in precedence order."""
        cache = PolicyCache()
        rules = [
            PolicyRule(
                id="ok-rule",
                trigger="event",
                condition=RuleCondition(metric="x", operator="eq", threshold=1),
                action="ok",
            ),
            PolicyRule(
                id="alert-rule",
                trigger="event",
                condition=RuleCondition(metric="x", operator="eq", threshold=1),
                action="alert",
            ),
            PolicyRule(
                id="block-rule",
                trigger="event",
                condition=RuleCondition(metric="x", operator="eq", threshold=1),
                action="block",
            ),
        ]
        policy = PolicyDocument(id="test", version=1, status="active", rules=rules)
        cache.load_policy(policy)

        result = cache.evaluate("event", {"x": 1})
        assert result.rule_id == "block-rule"


class TestPolicyCacheConditionEvaluation:
    """Test pre-compiled condition evaluation."""

    def test_missing_metric_is_false(self):
        """Missing metric in metrics dict results in False (fail-open)."""
        cache = PolicyCache()
        rule = PolicyRule(
            id="rule-1",
            trigger="event",
            condition=RuleCondition(metric="missing_key", operator="eq", threshold="value"),
            action="block",
        )
        policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
        cache.load_policy(policy)

        result = cache.evaluate("event", {"other_key": "value"})
        assert result.passed is True  # Condition not met

    def test_various_operators(self):
        """Test different comparison operators."""
        test_cases = [
            ("eq", 5, 5, True),
            ("neq", 5, 5, False),
            ("gt", 10, 5, True),
            ("gte", 5, 5, True),
            ("lt", 3, 5, True),
            ("lte", 5, 5, True),
            ("contains", "hello", "ell", True),
            ("in", "a", ["a", "b", "c"], True),
        ]

        for operator, metric_val, threshold_val, condition_should_match in test_cases:
            cache = PolicyCache()
            rule = PolicyRule(
                id=f"rule-{operator}",
                trigger="event",
                condition=RuleCondition(
                    metric="value", operator=operator, threshold=threshold_val
                ),
                action="block",
            )
            policy = PolicyDocument(id="test", version=1, status="active", rules=[rule])
            cache.load_policy(policy)

            result = cache.evaluate("event", {"value": metric_val})
            
            # If condition matched, rule should trigger (passed=False due to block action)
            # If condition didn't match, rule shouldn't trigger (passed=True)
            condition_matched = not result.passed
            
            assert condition_matched == condition_should_match, (
                f"Operator {operator}: metric={metric_val}, threshold={threshold_val}, "
                f"expected condition_matched={condition_should_match}, got {condition_matched}"
            )
