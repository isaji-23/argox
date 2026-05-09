"""
Policy Parser and Schema Validation Module

This module provides YAML policy parsing, schema validation, and predicate compilation
for the Argox governance framework. Policies are loaded from YAML, validated against
a strict schema, and compiled into fast, in-memory predicates suitable for evaluation
in the hot path (target: < 200 microseconds per evaluation).
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Schema Models (Pydantic)
# ============================================================================


class RuleCondition(BaseModel):
    """
    Represents a single condition in a policy rule.
    
    Attributes:
        metric: The metric or context key to evaluate (e.g., 'agent.cost.daily_total_usd').
        operator: Comparison operator ('eq', 'gt', 'gte', 'lt', 'lte', 'contains').
        threshold: The value to compare against (can be int, float, str, etc.).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    metric: str = Field(..., description="Metric or context key to evaluate")
    operator: Literal["eq", "gt", "gte", "lt", "lte", "contains"] = Field(
        ..., description="Comparison operator"
    )
    threshold: Any = Field(..., description="Value to compare against")


class PolicyRule(BaseModel):
    """
    Represents a single rule within a policy document.
    
    Attributes:
        id: Unique identifier for the rule.
        trigger: The event that triggers this rule (e.g., 'on_llm_call').
        condition: The RuleCondition that determines if the rule applies.
        action: The action to take ('block', 'alert', 'ok').
        enforcement: Enforcement level (default: 'strict').
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., description="Unique rule identifier")
    trigger: str = Field(..., description="Event that triggers this rule")
    condition: RuleCondition = Field(..., description="Condition to evaluate")
    action: Literal["block", "alert", "ok"] = Field(..., description="Action to take")
    enforcement: str = Field(default="strict", description="Enforcement level")


class PolicyDocument(BaseModel):
    """
    Represents a complete policy document loaded from YAML.
    
    Attributes:
        id: Unique policy identifier.
        version: Policy version number.
        status: Policy status (e.g., 'active', 'inactive').
        rules: List of PolicyRule objects.
        created_by: Optional creator email or identifier.
        updated_at: Optional ISO 8601 timestamp of last update.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., description="Unique policy identifier")
    version: int = Field(..., description="Policy version")
    status: str = Field(..., description="Policy status")
    rules: List[PolicyRule] = Field(..., description="List of policy rules")
    created_by: str | None = Field(default=None, description="Creator identifier")
    updated_at: str | None = Field(default=None, description="Last update timestamp (ISO 8601)")


# ============================================================================
# Predicate Compilation
# ============================================================================


def compile_condition(condition: RuleCondition) -> Callable[[Dict[str, Any]], bool]:
    """
    Compiles a RuleCondition into a fast, in-memory predicate function.
    
    This function generates a closure that captures the metric, operator, and threshold.
    The returned predicate is optimized for hot-path evaluation, with typical execution
    time under 200 microseconds per evaluation.
    
    Args:
        condition: A RuleCondition object specifying the metric, operator, and threshold.
    
    Returns:
        A callable that takes a metrics dictionary and returns a boolean indicating
        whether the condition is satisfied.
    
    Raises:
        ValueError: If the operator is not supported.
    
    Example:
        >>> cond = RuleCondition(
        ...     metric='agent.cost.daily_total_usd',
        ...     operator='gte',
        ...     threshold=50.0
        ... )
        >>> predicate = compile_condition(cond)
        >>> predicate({'agent.cost.daily_total_usd': 75.5})
        True
    """

    metric = condition.metric
    operator = condition.operator
    threshold = condition.threshold

    # Define operator functions (inline for performance)
    operator_funcs: Dict[str, Callable[[Any, Any], bool]] = {
        "eq": lambda a, b: a == b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
        "contains": lambda a, b: b in a if isinstance(a, (list, str, dict)) else False,
    }

    if operator not in operator_funcs:
        raise ValueError(f"Unsupported operator: {operator}")

    op_func = operator_funcs[operator]

    def predicate(metrics: Dict[str, Any]) -> bool:
        """Evaluate the condition against the given metrics dictionary."""
        value = metrics.get(metric)
        if value is None:
            return False
        return op_func(value, threshold)

    return predicate


# ============================================================================
# PolicyParser Class
# ============================================================================


class PolicyParser:
    """
    Loads, parses, and validates YAML policy files.
    
    This parser handles:
    - Reading YAML files from disk or strings
    - Validating structure against the PolicyDocument schema
    - Providing strict type checking via Pydantic
    
    Example:
        >>> parser = PolicyParser()
        >>> policy = parser.parse_file('policies/cost_control.yaml')
        >>> print(policy.id)
        'pol_01HXYZ'
    """

    def parse_yaml(self, yaml_content: str) -> PolicyDocument:
        """
        Parse and validate a YAML policy string.
        
        Args:
            yaml_content: Raw YAML string containing the policy definition.
        
        Returns:
            A validated PolicyDocument object.
        
        Raises:
            yaml.YAMLError: If the YAML is malformed.
            ValueError: If the parsed data does not match the PolicyDocument schema.
        """
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML: {e}") from e

        if data is None:
            raise ValueError("YAML content is empty")

        try:
            policy = PolicyDocument(**data)
        except Exception as e:
            raise ValueError(f"Policy validation failed: {e}") from e

        return policy

    def parse_file(self, file_path: str) -> PolicyDocument:
        """
        Load and parse a YAML policy file from disk.
        
        Args:
            file_path: Path to the YAML policy file.
        
        Returns:
            A validated PolicyDocument object.
        
        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file cannot be parsed or validated.
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {file_path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                yaml_content = f.read()
        except IOError as e:
            raise ValueError(f"Failed to read policy file: {e}") from e

        return self.parse_yaml(yaml_content)
