from typing import Annotated

from connhex.schemas.rules_engine import (
    Condition,
    Notification,
    PagedRuleEvents,
    PagedRules,
    Processable,
    Rule,
    RuleSeverity,
    RuleSort,
    RuleStatus,
    Tag,
)
from mcp.types import ToolAnnotations

from connhex_mcp.client import get_connhex
from connhex_mcp.mcp_instance import mcp


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, exclude_none=True)


@mcp.tool(
    title="List Rules",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def list_rules(
    ids: Annotated[list[str] | None, "Filter by specific rule IDs."] = None,
    tag_labels: Annotated[list[str] | None, "Filter by tag labels."] = None,
    tag_label_values: Annotated[
        list[str] | None, "Filter by tag label values."
    ] = None,
    severity: Annotated[RuleSeverity | None, "Filter by severity."] = None,
    status: Annotated[RuleStatus | None, "Filter by status."] = None,
    page: Annotated[int, "Page number (0-indexed)."] = 0,
    page_size: Annotated[int, "Results per page (default 1000)."] = 1000,
    sort: RuleSort = "createdAt:desc",
) -> PagedRules:
    """List rules from the Connhex Rules Engine."""
    return await get_connhex().rules.list_rules(
        ids=ids,
        tag_labels=tag_labels,
        tag_label_values=tag_label_values,
        severity=severity,
        status=status,
        page=page,
        page_size=page_size,
        sort=sort,
    )


@mcp.tool(
    title="Get Rule",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def get_rule(rule_id: Annotated[str, "Rule ID."]) -> Rule:
    """Get a single rule by ID from the Connhex Rules Engine."""
    return await get_connhex().rules.get_rule(rule_id)


@mcp.tool(
    title="Create Rule",
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=True
    ),
)
async def create_rule(
    name: Annotated[str, "Human-readable rule name."],
    notification: Notification,
    conditions: Annotated[
        list[Condition],
        "All conditions must hold for the rule to trigger.",
    ],
    severity: RuleSeverity | None = None,
    description: Annotated[str | None, "Optional description."] = None,
    processable: Annotated[
        Processable | None,
        'Whether the rule is processed (default "enabled").',
    ] = None,
    tags: list[Tag] | None = None,
) -> Rule:
    """Create a new rule in the Connhex Rules Engine."""
    payload: dict = {
        "name": name,
        "notification": _dump(notification),
        "conditions": [_dump(c) for c in conditions],
    }
    if severity is not None:
        payload["severity"] = severity
    if description is not None:
        payload["description"] = description
    if processable is not None:
        payload["processable"] = processable
    if tags is not None:
        payload["tags"] = [_dump(t) for t in tags]

    return await get_connhex().rules.create_rule(payload)


@mcp.tool(
    title="Update Rule",
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=True
    ),
)
async def update_rule(
    rule_id: Annotated[str, "Rule ID."],
    name: Annotated[str | None, "New name."] = None,
    notification: Notification | None = None,
    conditions: Annotated[
        list[Condition] | None,
        "Replace the rule's conditions.",
    ] = None,
    severity: RuleSeverity | None = None,
    description: Annotated[str | None, "New description."] = None,
    processable: Processable | None = None,
    tags: list[Tag] | None = None,
) -> Rule:
    """Partially update a rule. Only the fields provided are changed."""
    payload: dict = {}
    if name is not None:
        payload["name"] = name
    if notification is not None:
        payload["notification"] = _dump(notification)
    if conditions is not None:
        payload["conditions"] = [_dump(c) for c in conditions]
    if severity is not None:
        payload["severity"] = severity
    if description is not None:
        payload["description"] = description
    if processable is not None:
        payload["processable"] = processable
    if tags is not None:
        payload["tags"] = [_dump(t) for t in tags]

    return await get_connhex().rules.update_rule(rule_id, payload)


@mcp.tool(
    title="Delete Rule",
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
)
async def delete_rule(
    rule_id: Annotated[str, "Rule ID."],
) -> str:
    """Delete a rule. This action is irreversible."""
    await get_connhex().rules.delete_rule(rule_id)
    return f"Rule {rule_id} deleted successfully."


@mcp.tool(
    title="List Rule Events",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def list_rule_events(
    rule_ids: Annotated[list[str] | None, "Filter by rule IDs."] = None,
    from_date: Annotated[
        str | None, "ISO-8601 date-time lower bound (inclusive)."
    ] = None,
    to_date: Annotated[
        str | None, "ISO-8601 date-time upper bound (inclusive)."
    ] = None,
    status: Annotated[RuleStatus | None, "Filter by event status."] = None,
    page: Annotated[int, "Page number (0-indexed)."] = 0,
    page_size: Annotated[int, "Results per page (default 1000)."] = 1000,
    sort: RuleSort = "createdAt:desc",
) -> PagedRuleEvents:
    """List rule events (triggered rule occurrences)."""
    return await get_connhex().rules.list_rule_events(
        rule_ids=rule_ids,
        from_date=from_date,
        to_date=to_date,
        status=status,
        page=page,
        page_size=page_size,
        sort=sort,
    )
