from deployment_agent.tools.request_intent import (
    requests_ci_configuration,
    requests_dockerfile,
)


def test_dockerfile_create_intent_is_recognized():
    assert requests_dockerfile("Create a Dockerfile for the Angular app")
    assert requests_dockerfile("Please update Dockerfile to use the template")
    assert not requests_dockerfile("What does the Dockerfile do?")


def test_ci_change_intent_is_recognized():
    assert requests_ci_configuration("Create CI for the project")
    assert requests_ci_configuration("Add a GitHub Actions workflow")
    assert not requests_ci_configuration("What is the current CI workflow?")
