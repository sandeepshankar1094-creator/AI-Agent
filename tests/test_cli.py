import pytest

from deployment_agent.agent.graph import run_agent


def test_repository_argument_must_be_owner_and_repo():
    with pytest.raises(ValueError, match="OWNER/REPOSITORY"):
        run_agent("not-a-repository", "deploy it")
