"""
In-process local policy cache for hot-path policy evaluation.

This module implements a high-performance policy cache that stores compiled policy rules
indexed by trigger events, enabling O(1) lookups during the critical hot-path callbacks
of tracing processors (e.g., OpenAI Agents SDK TracingProcessor). Pre-compiled conditions
are stored as Python callables to minimize latency and meet the sub-200 microsecond
evaluation budget for native SDK integration.

**Design Note**: PolicyCache is the internal hot-path evaluation layer of the future
async SsePolicyClient. The cache itself is synchronous to meet latency requirements.
External policy evaluation continues via the async PolicyClient interface.

**Fail-open behavior (MVP)**: When a metric is missing from the span data, conditions
evaluate to False (rule not triggered). Strict enforcement (fail-closed) is pending.
"""

from typing import Any, Callable, Dict, List, Tuple, TypeAlias

from argox.interfaces.policy import PolicyResult
from argox.policies.parser import PolicyDocument, PolicyRule, compile_condition

# Type alias for rule index: maps trigger events to (rule, predicate) pairs
RuleIndex: TypeAlias = Dict[str, List[Tuple[PolicyRule, Callable[[Dict[str, Any]], bool]]]]


class PolicyCache:
    """
    In-process local policy cache for evaluating compiled rules against live span metrics.

    The cache stores policy rules indexed by their trigger events (e.g., 'on_llm_call',
    'on_tool_call') to achieve O(1) lookups during hot-path evaluation. Each rule's
    condition is pre-compiled into a callable predicate, eliminating parsing overhead.

    Attributes:
        _rules_by_trigger: Dictionary mapping trigger event names to lists of
            (rule, predicate) tuples for efficient event-based lookup.
    """

    def __init__(self) -> None:
        """Initialize the policy cache with an empty rules index."""
        self._rules_by_trigger: RuleIndex = {}

    def load_policy(self, policy: PolicyDocument) -> None:
        """
        Load a policy document and compile rules into the cache.

        Builds a new index in a local dictionary first, then performs an atomic
        assignment to avoid race conditions during concurrent evaluate() calls.
        All rule conditions are compiled before the swap to ensure cache coherency
        if compilation fails.

        Args:
            policy: A PolicyDocument instance containing rules to be cached and indexed.

        Raises:
            ValueError: If any rule's condition compilation fails (e.g., unknown operator).
                        The cache remains unchanged if this occurs.
        """
        # Build new index locally before atomic swap
        new_rules_by_trigger: RuleIndex = {}

        for rule in policy.rules:
            # Compile the condition expression into a callable predicate
            # This may raise ValueError if the condition is malformed
            predicate = compile_condition(rule.condition)

            # Index the rule by its trigger event for O(1) lookup
            if rule.trigger not in new_rules_by_trigger:
                new_rules_by_trigger[rule.trigger] = []

            new_rules_by_trigger[rule.trigger].append((rule, predicate))

        # Atomic swap: if we reach here, compilation succeeded
        self._rules_by_trigger = new_rules_by_trigger

    def evaluate(
        self, trigger: str, metrics: Dict[str, Any]
    ) -> PolicyResult:
        """
        Evaluate policies for a given trigger event against the provided metrics.

        Blocks take precedence over alerts. If any rule action is "block" and its
        condition matches, evaluation stops immediately. Alerts are collected; if
        no blocks are found, the first alert is returned. Rules with action "ok"
        are skipped (no-op).

        Args:
            trigger: The trigger event name (e.g., 'on_llm_call', 'on_tool_call').
            metrics: Dictionary of span metrics to evaluate against policy conditions.

        Returns:
            PolicyResult with passed=False if a blocking rule matched, passed=True
            with a warning reason if an alert matched, or PolicyResult.ok() otherwise.
        """
        rules_for_trigger = self._rules_by_trigger.get(trigger, [])
        alert_result = None

        for rule, predicate in rules_for_trigger:
            if not predicate(metrics):
                continue

            if rule.action == "block":
                return PolicyResult.block(
                    reason=f"Policy violation: {rule.id}",
                    rule_id=rule.id,
                )
            elif rule.action == "alert":
                if alert_result is None:
                    alert_result = PolicyResult.alert(
                        reason=f"Policy alert: {rule.id}",
                        rule_id=rule.id,
                    )
            # action == "ok" or unknown actions are no-ops

        return alert_result if alert_result is not None else PolicyResult.ok()


