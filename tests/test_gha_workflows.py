from pathlib import Path

import pytest

from deployment_agent.tools.gha_workflows import generate_ci_cd_pipeline


_TEMPLATE_ROOT = Path("templates/GHA-Workflows")


@pytest.mark.parametrize(
    ("project", "tree"),
    [
        (
            "Maven",
            [
                {"path": "pom.xml", "type": "blob"},
                {"path": "src/main/java/App.java", "type": "blob"},
            ],
        ),
        (
            "Angular",
            [
                {"path": "package.json", "type": "blob"},
                {"path": "angular.json", "type": "blob"},
                {"path": "src/main.ts", "type": "blob"},
            ],
        ),
    ],
)
def test_ci_cd_generation_uses_matching_workflow_templates(project, tree):
    state = {
        "repo": "sample-app",
        "requirement": "Create CI/CD pipeline",
        "default_branch": "develop",
        "tree": tree,
    }

    result = generate_ci_cd_pipeline(state)

    expected_ci = (_TEMPLATE_ROOT / project / "CI.yml").read_text(
        encoding="utf-8"
    )
    expected_cd = (_TEMPLATE_ROOT / project / "CD.yml").read_text(
        encoding="utf-8"
    )
    expected_ci = (
        expected_ci.replace('branches: [ "main" ]', 'branches: [ "develop" ]')
        .replace("      - main", '      - "develop"')
    )
    expected_cd = expected_cd.replace("      - main", '      - "develop"')

    assert result["generated_files"] == {
        ".github/workflows/ci.yml": expected_ci,
        ".github/workflows/cd.yml": expected_cd,
    }
    assert "validation_errors" not in result
    assert "deploy/chart/Chart.yaml" not in result["generated_files"]


def test_cd_pipeline_also_generates_shared_helm_repository_configuration():
    state = {
        "repo": "java-springboot",
        "requirement": "Create a CD pipeline",
        "default_branch": "main",
        "tree": [{"path": "pom.xml", "type": "blob"}],
    }

    result = generate_ci_cd_pipeline(state)

    assert set(result["generated_files"]) == {
        ".github/workflows/ci.yml",
        ".github/workflows/cd.yml",
    }
    assert set(result["external_generated_files"]) == {
        "Application/java/java-springboot/configmap.yaml",
        "Application/java/java-springboot/values.yaml",
    }


def test_ci_only_does_not_create_shared_helm_repository_files():
    state = {
        "repo": "java-springboot",
        "requirement": "Create a CI workflow",
        "default_branch": "main",
        "tree": [{"path": "pom.xml", "type": "blob"}],
    }

    result = generate_ci_cd_pipeline(state)

    assert "external_generated_files" not in result


def test_ci_cd_generation_rejects_projects_without_a_matching_template():
    state = {
        "repo": "sample-app",
        "requirement": "Create CI/CD pipeline",
        "default_branch": "main",
        "tree": [{"path": "requirements.txt", "type": "blob"}],
    }

    with pytest.raises(ValueError, match="templates are available for Maven and Angular"):
        generate_ci_cd_pipeline(state)
