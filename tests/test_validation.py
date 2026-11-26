import shutil

from deployment_agent.agent.models import DeploymentPlan
from deployment_agent.tools.yaml_validator import validate_files


def test_missing_validation_tools_are_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(
        "deployment_agent.tools.yaml_validator.sysconfig.get_path",
        lambda _: str(tmp_path),
    )
    plan = DeploymentPlan(application_name="sample-app")

    errors = validate_files(
        {},
        plan,
        source_files={"Dockerfile": "FROM scratch\n"},
    )

    assert any("yamllint is required" in error for error in errors)
    assert any("helm is required" in error for error in errors)
    assert any("Docker is required" in error for error in errors)
