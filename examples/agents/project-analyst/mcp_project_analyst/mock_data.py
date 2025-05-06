"""Mock data generation utilities for Project Analyst Agent.

This module provides functions to generate mock project issues for demonstration purposes.
"""

import random
from typing import Sequence, TypedDict


class Issue(TypedDict):
    """Representation of a project issue."""

    number: int
    title: str
    state: str
    priority: str
    type: str
    assignee: str
    effort: str
    description: str
    dependencies: str


# Mock data constants
ISSUE_TYPES = ["bug", "feature", "task", "improvement", "documentation"]
PRIORITIES = ["low", "medium", "high", "critical"]
STATES = ["open", "closed"]
ASSIGNEES = ["Alice", "Bob", "Charlie", "Diana", "Unassigned"]
EFFORTS = ["1 day", "3 days", "1 week", "2 weeks", "Unknown"]


def generate_mock_issues(project_name: str, count: int = 10) -> Sequence[Issue]:
    """
    Generate mock project issues for demonstration purposes.

    Args:
        project_name: The name of the project
        count: Number of issues to generate

    Returns:
        A sequence of mock issues
    """
    issues: list[Issue] = []
    for i in range(1, count + 1):
        # Weight state to have more open than closed
        state = random.choices(STATES, weights=[0.7, 0.3])[0]

        # Weight priority
        priority = random.choices(PRIORITIES, weights=[0.2, 0.4, 0.3, 0.1])[0]

        issue: Issue = {
            "number": i,
            "title": f"{random.choice(ISSUE_TYPES).capitalize()} for {project_name} component {random.randint(1, 5)}",
            "state": state,
            "priority": priority,
            "type": random.choice(ISSUE_TYPES),
            "assignee": random.choice(ASSIGNEES),
            "effort": random.choice(EFFORTS),
            "description": f"This is a mock issue for {project_name}. It requires attention and possibly refactoring of the existing code.",
            "dependencies": random.choice(
                [
                    "None",
                    f"Issue #{random.randint(1, count)}",
                    "External dependency on API",
                ]
            ),
        }
        issues.append(issue)

    return issues


def generate_analysis_report(
    project_name: str,
    issues: Sequence[Issue],
) -> str:
    """
    Generate a formatted analysis report from issue data.

    Args:
        project_name: The name of the project
        issues: The sequence of issues to analyze

    Returns:
        A formatted markdown report
    """
    # Process the issues
    open_issues = [issue for issue in issues if issue["state"] == "open"]
    open_count = len(open_issues)
    closed_count = len(issues) - open_count

    # Count priorities
    priorities: dict[str, int] = {}
    for issue in issues:
        priority = issue["priority"]
        priorities[priority] = priorities.get(priority, 0) + 1

    # Count by type
    types: dict[str, int] = {}
    for issue in issues:
        issue_type = issue["type"]
        types[issue_type] = types.get(issue_type, 0) + 1

    return f"""# Project Issues Analysis for {project_name}

## Summary
- Total issues analyzed: {len(issues)}
- Open issues: {open_count}
- Closed issues: {closed_count}

## Issues by Priority
{chr(10).join(f"- {priority}: {count}" for priority, count in priorities.items())}

## Issues by Type
{chr(10).join(f"- {issue_type}: {count}" for issue_type, count in types.items())}

## Top Open Issues
{chr(10).join(f"- #{issue['number']}: {issue['title']} (Priority: {issue['priority']})" for issue in open_issues[:5])}

## Recommended Next Steps
1. Address high priority issues first
2. Review issues with dependencies
3. Re-estimate effort for any issues that have been open for a long time
"""
