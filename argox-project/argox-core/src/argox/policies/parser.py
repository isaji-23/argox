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


# Schema Models (Pydantic)
class RuleCondition(BaseModel):
    """Represents a single condition in a policy rule."""
    model_config = ConfigDict(str_strip_whitespace=True)

    metric: str = Field(..., description="Metric or context key to evaluate")
    # UPDATE: Added 'neq' and 'in' to Literal
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains", "in"] = Field(
        ..., description="Comparison operator"
    )
    threshold: Any = Field(..., description="Value to compare against")


class PolicyRule(BaseModel):
    """Represents a single rule within a policy document."""
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., description="Unique rule identifier")
    trigger: str = Field(..., description="Event that triggers this rule")
    condition: RuleCondition = Field(..., description="Condition to evaluate")
    action: Literal["block", "alert", "ok"] = Field(..., description="Action to take")
    enforcement: str = Field(default="strict", description="Enforcement level")


class PolicyDocument(BaseModel):
    """Represents a complete policy document loaded from YAML."""
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., description="Unique policy identifier")
    version: int = Field(..., description="Policy version")
    # UPDATE: Changed 'str' to Literal for strict validation
    status: Literal["active", "draft", "archived"] = Field(..., description="Policy status")
    rules: List[PolicyRule] = Field(..., description="List of policy rules")
    created_by: str | None = Field(default=None, description="Creator identifier")
    updated_at: str | None = Field(default=None, description="Last update timestamp (ISO 8601)")


# Helper Functions
# UPDATE: Added helper for nested dictionaries
def _get_nested_value(d: Dict[str, Any], path: str) -> Any:
    """Safely retrieves a value from a nested dictionary using dot-notation."""
    keys = path.split('.')
    for key in keys:
        if isinstance(d, dict) and key in d:
            d = d[key]
        else:
            return None
    return d


# Predicate Compilation
def compile_condition(condition: RuleCondition) -> Callable[[Dict[str, Any]], bool]:
    """Compiles a RuleCondition into a fast, in-memory predicate function."""
    metric = condition.metric
    operator = condition.operator
    threshold = condition.threshold

    # Define operator functions (inline for performance)
    operator_funcs: Dict[str, Callable[[Any, Any], bool]] = {
        "eq": lambda a, b: a == b,
        "neq": lambda a, b: a != b, # UPDATE: Added neq
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
        "contains": lambda a, b: b in a if isinstance(a, (list, str, dict)) else False,
        "in": lambda a, b: a in b if isinstance(b, (list, set, tuple)) else False, # UPDATE: Added in
    }

    if operator not in operator_funcs:
        raise ValueError(f"Unsupported operator: {operator}")

    op_func = operator_funcs[operator]

    def predicate(metrics: Dict[str, Any]) -> bool:
        """Evaluate the condition against the given metrics dictionary."""
        # UPDATE: Use dot-notation resolver instead of dict.get()
        value = _get_nested_value(metrics, metric)
        
        if value is None:
            # UPDATE: Explicit documentation regarding missing metrics
            # A missing metric is treated as a condition not met (returns False).
            # For strict rules requiring the metric, this fail-open behavior 
            # might need to be revisited or enforced via schema elsewhere.
            return False
            
        return op_func(value, threshold)

    return predicate


# PolicyParser Class
class PolicyParser:
    """Loads, parses, and validates YAML policy files."""

    def parse_yaml(self, yaml_content: str) -> PolicyDocument:
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
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {file_path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                yaml_content = f.read()
        except IOError as e:
            raise ValueError(f"Failed to read policy file: {e}") from e

        return self.parse_yaml(yaml_content)