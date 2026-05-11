"""
In-process local policy cache for hot-path policy evaluation.

This module implements a high-performance policy cache that stores compiled policy rules
indexed by trigger events, enabling O(1) lookups during the critical hot-path callbacks
of tracing processors. Pre-compiled conditions are stored as Python callables to minimize
latency and meet the sub-200 microsecond evaluation budget for native SDK integration.
"""

from typing import Any, Callable, Dict, List, Tuple

from argox.interfaces.policy import PolicyResult
from argox.policies.parser import PolicyDocument, PolicyRule, compile_condition


class PolicyCache:
    """
    In-process local policy cache for evaluating compiled rules against live span metrics.

    The cache stores policy rules indexed by their trigger events (e.g., 'on_llm_call',
    'on_tool_call') to achieve O(1) lookups during hot-path evaluation. Each rule's
    condition is pre-compiled into a callable predicate, eliminating parsing overhead
    and ensuring deterministic sub-200 microsecond latency in the evaluation path.

    This design enables native SDK integration with tracing processors such as the
    OpenAI Agents SDK's TracingProcessor, allowing synchronous policy evaluation
    directly in the hot-path callbacks without introducing measurable latency overhead.

    Attributes:
        _rules_by_trigger: Dictionary mapping trigger event names to lists of
            (rule, predicate) tuples for efficient event-based lookup.
    """

    def __init__(self) -> None:
        """
        Initialize the policy cache with an empty rules index.

        The rules dictionary is indexed by trigger event name for O(1) access during
        evaluation.
        """
        self._rules_by_trigger: Dict[
            str, List[Tuple[PolicyRule, Callable[[Dict[str, Any]], bool]]]
        ] = {}

    def load_policy(self, policy: PolicyDocument) -> None:
        """
        Load a policy document and compile rules into the cache.

        Performs an atomic-like clear-and-rebuild of the cache from the provided
        policy document. Each rule's condition expression is compiled into a callable
        predicate and stored in the cache indexed by its trigger event. This ensures
        all downstream evaluate() calls use the latest policy definitions.

        Args:
            policy: A PolicyDocument instance containing rules to be cached and indexed.
        """
        # Clear and rebuild the cache atomically
        self._rules_by_trigger = {}

        for rule in policy.rules:
            # Compile the condition expression into a callable predicate
            predicate = compile_condition(rule.condition)

            # Index the rule by its trigger event for O(1) lookup
            if rule.trigger not in self._rules_by_trigger:
                self._rules_by_trigger[rule.trigger] = []

            self._rules_by_trigger[rule.trigger].append((rule, predicate))

    def evaluate(
        self, trigger: str, metrics: Dict[str, Any]
    ) -> PolicyResult:
        """
        Evaluate policies for a given trigger event against the provided metrics.

        Retrieves pre-compiled rules for the trigger and evaluates each predicate
        against the metrics. Blocks take precedence over alerts to ensure failed
        policies are caught immediately.

        Algorithm:
        1. Retrieve all rules indexed by trigger (O(1) lookup).
        2. Iterate rules and evaluate pre-compiled predicates against metrics.
        3. Return PolicyResult.block() immediately if any rule action is "block".
        4. Store the first alert encountered and continue checking for blocks.
        5. Return PolicyResult.alert() if only alerts were triggered.
        6. Return PolicyResult.ok() if no rules matched or no violations occurred.

        Args:
            trigger: The trigger event name (e.g., 'on_llm_call', 'on_tool_call').
            metrics: Dictionary of span metrics to evaluate against policy conditions.

        Returns:
            PolicyResult: One of:
                - PolicyResult.block(...) if a blocking rule matched.
                - PolicyResult.alert(...) if only alerting rules matched.
                - PolicyResult.ok() if no rules matched or all evaluations passed.
        """
        rules_for_trigger = self._rules_by_trigger.get(trigger, [])

        alert_result = None

        for rule, predicate in rules_for_trigger:
            # Evaluate the pre-compiled predicate against the metrics
            if predicate(metrics):
                if rule.action == "block":
                    # Block rules have priority; return immediately
                    return PolicyResult.block(
                        reason=f"Policy violation: {rule.id}",
                        rule_id=rule.id,
                    )
                elif rule.action == "alert":
                    # Store the first alert encountered but continue checking
                    # for blocks, since blocks take precedence
                    if alert_result is None:
                        alert_result = PolicyResult.alert(
                            reason=f"Policy alert: {rule.id}",
                            rule_id=rule.id,
                        )

        # If an alert was triggered and no block was found, return the alert
        if alert_result is not None:
            return alert_result

        # No violations or alerts; the action is allowed
        return PolicyResult.ok()
