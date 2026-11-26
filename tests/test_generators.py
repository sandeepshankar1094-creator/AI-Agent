import yaml
import pytest

from deployment_agent.agent.models import DeploymentPlan
from deployment_agent.tools.deployment_generator import generate_files


def test_generate_files_builds_parseable_workflow_and_chart():
    plan = DeploymentPlan(application_name="sample-app", container_port=9090)

    files = generate_files(plan, "Acme", "Sample", default_branch="trunk")

    workflow = yaml.safe_load(files[".github/workflows/deploy.yml"])
    chart = yaml.safe_load(files["deploy/chart/Chart.yaml"])
    values = yaml.safe_load(files["deploy/chart/values.yaml"])
    assert workflow["jobs"]["build-and-deploy"]["steps"]
    assert chart["name"] == "sample-app"
    assert values["service"]["port"] == 9090
    assert workflow["on"]["push"]["branches"] == ["trunk"]
    assert "image.tag" in files[".github/workflows/deploy.yml"]


def test_generated_workflow_wraps_long_repository_image_names():
    files = generate_files(
        DeploymentPlan(application_name="sample-app"),
        "very-long-enterprise-owner",
        "very-long-repository-name-that-causes-long-workflow-lines",
    )
    workflow = files[".github/workflows/deploy.yml"]

    assert all(len(line) <= 80 for line in workflow.splitlines())
    parsed = yaml.safe_load(workflow)
    steps = parsed["jobs"]["build-and-deploy"]["steps"]
    image_step = next(step for step in steps if step.get("name") == "Set image name")
    docker_step = next(step for step in steps if step.get("name") == "Build and push image")
    helm_step = next(step for step in steps if step.get("name") == "Deploy with Helm")
    assert "GITHUB_REPOSITORY" in image_step["run"]
    assert docker_step["with"]["tags"] == "${{ env.IMAGE_NAME }}:${{ github.sha }}"
    assert '--set image.repository="$IMAGE_NAME"' in helm_step["run"]


@pytest.mark.parametrize("path", ["../outside", "/absolute"])
def test_generator_rejects_paths_outside_repository(path):
    plan = DeploymentPlan(application_name="sample-app", chart_path=path)

    with pytest.raises(ValueError, match="safe repository-relative path"):
        generate_files(plan, "acme", "sample")


def test_generator_rejects_overlapping_output_paths():
    plan = DeploymentPlan(
        application_name="sample-app",
        workflow_path="deploy/chart/Chart.yaml",
    )

    with pytest.raises(ValueError, match="must not overlap"):
        generate_files(plan, "acme", "sample")
