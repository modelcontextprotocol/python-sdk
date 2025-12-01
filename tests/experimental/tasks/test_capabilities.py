"""Tests for tasks capability checking utilities."""

import pytest

from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.capabilities import (
    check_tasks_capability,
    has_task_augmented_elicitation,
    has_task_augmented_sampling,
    require_task_augmented_elicitation,
    require_task_augmented_sampling,
)
from mcp.types import (
    ClientCapabilities,
    ClientTasksCapability,
    ClientTasksRequestsCapability,
    TasksCreateElicitationCapability,
    TasksCreateMessageCapability,
    TasksElicitationCapability,
    TasksSamplingCapability,
)


class TestCheckTasksCapability:
    """Tests for check_tasks_capability function."""

    def test_required_requests_none_returns_true(self) -> None:
        """When required.requests is None, should return True."""
        required = ClientTasksCapability()
        client = ClientTasksCapability()
        assert check_tasks_capability(required, client) is True

    def test_client_requests_none_returns_false(self) -> None:
        """When client.requests is None but required.requests is set, should return False."""
        required = ClientTasksCapability(requests=ClientTasksRequestsCapability())
        client = ClientTasksCapability()
        assert check_tasks_capability(required, client) is False

    def test_elicitation_required_but_client_missing(self) -> None:
        """When elicitation is required but client doesn't have it."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(elicitation=TasksElicitationCapability())
        )
        client = ClientTasksCapability(requests=ClientTasksRequestsCapability())
        assert check_tasks_capability(required, client) is False

    def test_elicitation_create_required_but_client_missing(self) -> None:
        """When elicitation.create is required but client doesn't have it."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability())
            )
        )
        client = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability()  # No create
            )
        )
        assert check_tasks_capability(required, client) is False

    def test_elicitation_create_present(self) -> None:
        """When elicitation.create is required and client has it."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability())
            )
        )
        client = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability())
            )
        )
        assert check_tasks_capability(required, client) is True

    def test_sampling_required_but_client_missing(self) -> None:
        """When sampling is required but client doesn't have it."""
        required = ClientTasksCapability(requests=ClientTasksRequestsCapability(sampling=TasksSamplingCapability()))
        client = ClientTasksCapability(requests=ClientTasksRequestsCapability())
        assert check_tasks_capability(required, client) is False

    def test_sampling_create_message_required_but_client_missing(self) -> None:
        """When sampling.createMessage is required but client doesn't have it."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability())
            )
        )
        client = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                sampling=TasksSamplingCapability()  # No createMessage
            )
        )
        assert check_tasks_capability(required, client) is False

    def test_sampling_create_message_present(self) -> None:
        """When sampling.createMessage is required and client has it."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability())
            )
        )
        client = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability())
            )
        )
        assert check_tasks_capability(required, client) is True

    def test_both_elicitation_and_sampling_present(self) -> None:
        """When both elicitation.create and sampling.createMessage are required and client has both."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability()),
                sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability()),
            )
        )
        client = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability()),
                sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability()),
            )
        )
        assert check_tasks_capability(required, client) is True

    def test_elicitation_without_create_required(self) -> None:
        """When elicitation is required but not create specifically."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability()  # No create
            )
        )
        client = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability())
            )
        )
        assert check_tasks_capability(required, client) is True

    def test_sampling_without_create_message_required(self) -> None:
        """When sampling is required but not createMessage specifically."""
        required = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                sampling=TasksSamplingCapability()  # No createMessage
            )
        )
        client = ClientTasksCapability(
            requests=ClientTasksRequestsCapability(
                sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability())
            )
        )
        assert check_tasks_capability(required, client) is True


class TestHasTaskAugmentedElicitation:
    """Tests for has_task_augmented_elicitation function."""

    def test_tasks_none(self) -> None:
        """Returns False when caps.tasks is None."""
        caps = ClientCapabilities()
        assert has_task_augmented_elicitation(caps) is False

    def test_requests_none(self) -> None:
        """Returns False when caps.tasks.requests is None."""
        caps = ClientCapabilities(tasks=ClientTasksCapability())
        assert has_task_augmented_elicitation(caps) is False

    def test_elicitation_none(self) -> None:
        """Returns False when caps.tasks.requests.elicitation is None."""
        caps = ClientCapabilities(tasks=ClientTasksCapability(requests=ClientTasksRequestsCapability()))
        assert has_task_augmented_elicitation(caps) is False

    def test_create_none(self) -> None:
        """Returns False when caps.tasks.requests.elicitation.create is None."""
        caps = ClientCapabilities(
            tasks=ClientTasksCapability(
                requests=ClientTasksRequestsCapability(elicitation=TasksElicitationCapability())
            )
        )
        assert has_task_augmented_elicitation(caps) is False

    def test_create_present(self) -> None:
        """Returns True when full capability path is present."""
        caps = ClientCapabilities(
            tasks=ClientTasksCapability(
                requests=ClientTasksRequestsCapability(
                    elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability())
                )
            )
        )
        assert has_task_augmented_elicitation(caps) is True


class TestHasTaskAugmentedSampling:
    """Tests for has_task_augmented_sampling function."""

    def test_tasks_none(self) -> None:
        """Returns False when caps.tasks is None."""
        caps = ClientCapabilities()
        assert has_task_augmented_sampling(caps) is False

    def test_requests_none(self) -> None:
        """Returns False when caps.tasks.requests is None."""
        caps = ClientCapabilities(tasks=ClientTasksCapability())
        assert has_task_augmented_sampling(caps) is False

    def test_sampling_none(self) -> None:
        """Returns False when caps.tasks.requests.sampling is None."""
        caps = ClientCapabilities(tasks=ClientTasksCapability(requests=ClientTasksRequestsCapability()))
        assert has_task_augmented_sampling(caps) is False

    def test_create_message_none(self) -> None:
        """Returns False when caps.tasks.requests.sampling.createMessage is None."""
        caps = ClientCapabilities(
            tasks=ClientTasksCapability(requests=ClientTasksRequestsCapability(sampling=TasksSamplingCapability()))
        )
        assert has_task_augmented_sampling(caps) is False

    def test_create_message_present(self) -> None:
        """Returns True when full capability path is present."""
        caps = ClientCapabilities(
            tasks=ClientTasksCapability(
                requests=ClientTasksRequestsCapability(
                    sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability())
                )
            )
        )
        assert has_task_augmented_sampling(caps) is True


class TestRequireTaskAugmentedElicitation:
    """Tests for require_task_augmented_elicitation function."""

    def test_raises_when_none(self) -> None:
        """Raises McpError when client_caps is None."""
        with pytest.raises(McpError) as exc_info:
            require_task_augmented_elicitation(None)
        assert "task-augmented elicitation" in str(exc_info.value)

    def test_raises_when_missing(self) -> None:
        """Raises McpError when capability is missing."""
        caps = ClientCapabilities()
        with pytest.raises(McpError) as exc_info:
            require_task_augmented_elicitation(caps)
        assert "task-augmented elicitation" in str(exc_info.value)

    def test_passes_when_present(self) -> None:
        """Does not raise when capability is present."""
        caps = ClientCapabilities(
            tasks=ClientTasksCapability(
                requests=ClientTasksRequestsCapability(
                    elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability())
                )
            )
        )
        require_task_augmented_elicitation(caps)


class TestRequireTaskAugmentedSampling:
    """Tests for require_task_augmented_sampling function."""

    def test_raises_when_none(self) -> None:
        """Raises McpError when client_caps is None."""
        with pytest.raises(McpError) as exc_info:
            require_task_augmented_sampling(None)
        assert "task-augmented sampling" in str(exc_info.value)

    def test_raises_when_missing(self) -> None:
        """Raises McpError when capability is missing."""
        caps = ClientCapabilities()
        with pytest.raises(McpError) as exc_info:
            require_task_augmented_sampling(caps)
        assert "task-augmented sampling" in str(exc_info.value)

    def test_passes_when_present(self) -> None:
        """Does not raise when capability is present."""
        caps = ClientCapabilities(
            tasks=ClientTasksCapability(
                requests=ClientTasksRequestsCapability(
                    sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability())
                )
            )
        )
        require_task_augmented_sampling(caps)
