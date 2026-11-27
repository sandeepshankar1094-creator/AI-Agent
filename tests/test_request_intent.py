from deployment_agent.tools.request_intent import (
    requests_cd_configuration,
    requests_ci_configuration,
    requests_dockerfile,
    requests_helm_chart,
    requests_helm_secret_configuration,
    requests_helm_parameter_update,
)


def test_dockerfile_create_intent_is_recognized():
    assert requests_dockerfile("Create a Dockerfile for the Angular app")
    assert requests_dockerfile("Please update Dockerfile to use the template")
    assert not requests_dockerfile("What does the Dockerfile do?")


def test_ci_change_intent_is_recognized():
    assert requests_ci_configuration("Create CI for the project")
    assert requests_ci_configuration("Add a GitHub Actions workflow")
    assert not requests_ci_configuration("What is the current CI workflow?")


def test_helm_chart_change_intent_is_recognized():
    assert requests_helm_chart("Create helm charts for this application")
    assert requests_helm_chart("Generate a Helm chart")
    assert requests_helm_chart("Helm chart creation")
    assert requests_helm_chart("Set app.replicaCount in values.yaml")
    assert requests_helm_chart("Increase replicas to 3")
    assert not requests_helm_chart("Explain the Helm chart")


def test_cd_change_intent_is_recognized():
    assert requests_cd_configuration("Create CD")
    assert requests_cd_configuration("CD pipeline creation")
    assert requests_cd_configuration("Create a CI/CD pipeline")
    assert not requests_cd_configuration("Explain the CD pipeline")


def test_helm_secret_change_intent_is_recognized():
    assert requests_helm_secret_configuration(
        "Add this api-key into poc-ai-agent service"
    )
    assert requests_helm_secret_configuration("Add secret named database-password")
    assert not requests_helm_secret_configuration("Explain the api key configuration")
    assert requests_helm_secret_configuration("Remove secret named api-key")


def test_helm_endpoint_and_redis_changes_are_parameter_updates():
    assert requests_helm_parameter_update(
        "Set the HTTPS destination to api.example.com"
    )
    assert requests_helm_parameter_update("Update the Redis URL to cache.example.net")


def test_spaced_autoscale_minimum_update_is_recognized():
    requirements = (
        "Update the auto scale min value also to 5",
        "Set autoscaling minimum to 5",
        "Increase the minimum autoscaling value to 5",
        "Set minimum replicas to 3",
    )
    for requirement in requirements:
        assert requests_helm_chart(requirement)
        assert requests_helm_parameter_update(requirement)
