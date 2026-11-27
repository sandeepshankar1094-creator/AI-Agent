from pathlib import Path

import pytest
import yaml

from deployment_agent.agent.models import DeploymentPlan
from deployment_agent.tools.deployment import (
    generate_deployment_files,
    generate_dockerfile_only,
    generate_helm_chart_only,
)
from deployment_agent.tools.dockerfile import generate_project_dockerfile


class FakeGitHubClient:
    def __init__(self, contents):
        self.contents = contents
        self.requested = []

    def get_file(self, owner, repo, path, ref):
        self.requested.append((owner, repo, path, ref))
        return self.contents.get(path)


def _tree(*paths):
    return [{"path": path, "type": "blob"} for path in paths]


def test_maven_project_uses_maven_dockerfile_template():
    plan = DeploymentPlan(application_name="java-app", create_dockerfile=True)
    client = FakeGitHubClient({"pom.xml": "<project/>"})

    updated_plan, files = generate_project_dockerfile(
        plan,
        _tree("pom.xml", "src/main/java/App.java"),
        "acme",
        "service",
        "trunk",
        client,
    )

    template = Path("templates/Dockerfiles/Maven").read_text(encoding="utf-8")
    assert files == {"Dockerfile": template}
    assert "FROM maven:" not in template
    assert "COPY target/*.jar app.jar" in template
    assert updated_plan.dockerfile_path == "Dockerfile"
    assert client.requested == [("acme", "service", "pom.xml", "trunk")]


def test_dockerfile_only_generation_skips_deployment_files():
    client = FakeGitHubClient({"pom.xml": "<project/>"})
    state = {
        "tree": _tree("pom.xml"),
        "owner": "acme",
        "repo": "service",
        "default_branch": "main",
    }

    result = generate_dockerfile_only(state, client)

    assert result["generated_files"].keys() == {"Dockerfile"}
    assert "workflow_path" not in result["generated_files"]
    assert "validation_errors" not in result
    assert result["plan"].create_dockerfile


def test_helm_chart_only_generation_targets_shared_chart_repository():
    state = {
        "repo": "java-springboot",
    }

    result = generate_helm_chart_only(state)

    assert set(result["external_generated_files"]) == {
        "Application/java/java-springboot/configmap.yaml",
        "Application/java/java-springboot/values.yaml",
    }
    assert "validation_errors" not in result
    assert "generated_files" not in result
    configmap = yaml.safe_load(
        result["external_generated_files"][
            "Application/java/java-springboot/configmap.yaml"
        ]
    )
    values = yaml.safe_load(
        result["external_generated_files"][
            "Application/java/java-springboot/values.yaml"
        ]
    )
    assert configmap["app_name"] == "java-springboot"
    assert values["app"]["containers"]["image"] == "java-springboot"
    assert values["app"]["labels"]["project"] == "java"
    assert values["service"]["labels"]["app"] == "java-springboot"


def test_angular_project_uses_node_template_and_build_output_path():
    plan = DeploymentPlan(application_name="web-app", create_dockerfile=True)
    client = FakeGitHubClient(
        {
            "package.json": '{"name":"web-app","scripts":{"build":"ng build"}}',
            "angular.json": (
                '{"projects":{"web-app":{"architect":{"build":{"options":'
                '{"outputPath":"dist/web-app/browser"}}}}}}'
            ),
        }
    )

    _, files = generate_project_dockerfile(
        plan,
        _tree("package.json", "angular.json", "src/main.ts"),
        "acme",
        "web",
        "main",
        client,
    )

    dockerfile = files["Dockerfile"]
    expected_template = Path("templates/Dockerfiles/Node").read_text(
        encoding="utf-8"
    )
    assert dockerfile == expected_template.replace(
        "{{ANGULAR_OUTPUT_PATH}}", "dist/web-app/browser"
    ).replace("RUN npm ci", "RUN npm install")
    assert "FROM node:20-alpine AS build" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert (
        "COPY --from=build /app/dist/web-app/browser /usr/share/nginx/html"
        in dockerfile
    )
    assert "{{" not in dockerfile


def test_angular_project_is_selected_over_workspace_package_manifest():
    plan = DeploymentPlan(application_name="web-app", create_dockerfile=True)
    client = FakeGitHubClient(
        {
            "apps/web/package.json": (
                '{"name":"web-app","scripts":{"build":"ng build"}}'
            ),
            "apps/web/angular.json": (
                '{"projects":{"web-app":{"architect":{"build":{"options":'
                '{"outputPath":"dist/web-app/browser"}}}}}}'
            ),
        }
    )

    updated_plan, files = generate_project_dockerfile(
        plan,
        _tree(
            "package.json",
            "package-lock.json",
            "apps/web/package.json",
            "apps/web/angular.json",
        ),
        "acme",
        "web",
        "main",
        client,
    )

    assert updated_plan.build_context == "apps/web"
    assert "COPY --from=build /app/dist/web-app/browser" in files["apps/web/Dockerfile"]
    assert ("acme", "web", "apps/web/package.json", "main") in client.requested


def test_node_server_uses_node_runtime_and_npm_start():
    plan = DeploymentPlan(
        application_name="api",
        container_port=3000,
        create_dockerfile=True,
    )
    client = FakeGitHubClient(
        {"package.json": '{"name":"api","scripts":{"start":"node server.js"}}'}
    )

    _, files = generate_project_dockerfile(
        plan,
        _tree("package.json", "server.js"),
        "acme",
        "api",
        "main",
        client,
    )

    dockerfile = files["Dockerfile"]
    expected_template = Path("templates/Dockerfiles/NodeServer").read_text(
        encoding="utf-8"
    )
    assert dockerfile == (
        expected_template.replace("{{INSTALL_COMMAND}}", "npm install")
        .replace("{{BUILD_STEP}}", "# No build step")
        .replace("{{CONTAINER_PORT}}", "3000")
    )
    assert "ENV PORT=3000" in dockerfile
    assert 'CMD ["npm", "start"]' in dockerfile
    assert "RUN npm run build" not in dockerfile


def test_dockerfile_generation_updates_workflow_context_and_dockerfile():
    plan = DeploymentPlan(
        application_name="java-app",
        build_context="backend",
        create_dockerfile=True,
    )
    client = FakeGitHubClient({"backend/pom.xml": "<project/>"})
    state = {
        "plan": plan,
        "tree": _tree("backend/pom.xml"),
        "owner": "acme",
        "repo": "service",
        "default_branch": "main",
    }

    result = generate_deployment_files(state, client)
    workflow = yaml.safe_load(
        result["generated_files"][".github/workflows/deploy.yml"]
    )
    build_step = next(
        step
        for step in workflow["jobs"]["build-and-deploy"]["steps"]
        if step.get("name") == "Build and push image"
    )

    assert "backend/Dockerfile" in result["generated_files"]
    assert build_step["with"]["context"] == "backend"
    assert build_step["with"]["file"] == "backend/Dockerfile"
    assert result["source_files"] == {}
    assert "FROM maven:" not in result["generated_files"]["backend/Dockerfile"]


def test_dockerfile_generation_rejects_non_project_repository():
    plan = DeploymentPlan(application_name="unknown-app", create_dockerfile=True)
    client = FakeGitHubClient({})

    with pytest.raises(ValueError, match="No Maven pom.xml, Node package.json"):
        generate_project_dockerfile(
            plan, _tree("README.md"), "acme", "service", "main", client
        )


def test_dockerfile_generation_updates_existing_file_from_template():
    plan = DeploymentPlan(application_name="java-app", create_dockerfile=True)
    client = FakeGitHubClient({"pom.xml": "<project/>"})

    _, files = generate_project_dockerfile(
        plan, _tree("pom.xml", "Dockerfile"), "acme", "service", "main", client
    )
    assert "Dockerfile" in files
