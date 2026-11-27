import shutil

import pytest

from deployment_agent.agent.models import (
    DeploymentPlan,
    ValidationRepairResponse,
)
from deployment_agent.tools.validation import (
    MAX_VALIDATION_REPAIR_ATTEMPTS,
    repair_validation_errors,
    should_attempt_validation_repair,
)
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


def test_validation_repair_is_bounded_and_skips_environment_failures():
    assert should_attempt_validation_repair(
        {"validation_errors": ["helm template failed: invalid chart"]}
    )
    assert not should_attempt_validation_repair(
        {"validation_errors": ["helm is required but was not found on PATH"]}
    )
    assert not should_attempt_validation_repair(
        {
            "validation_errors": ["yamllint failed: parse error"],
            "repair_attempt": MAX_VALIDATION_REPAIR_ATTEMPTS,
        }
    )


def test_yaml_repair_preserves_existing_key_vault_references():
    original = """app:
  containers:
    env:
      - name: api-key
        value: api-key@azurekeyvault
  kvSecrets:
    - api-key
"""
    repaired = """app:
  replicaCount: 2
  containers:
    env:
      - name: api-key
        value: api-key@azurekeyvault
  kvSecrets:
    - api-key
"""

    class FakeModel:
        def invoke(self, prompt):
            assert "helm template failed" in prompt
            return ValidationRepairResponse(
                updated_files={"values.yaml": repaired}
            )

    result = repair_validation_errors(
        {
            "generated_files": {"values.yaml": original},
            "validation_errors": ["helm template failed: invalid chart"],
        },
        FakeModel(),
    )

    assert result["generated_files"]["values.yaml"] == repaired
    assert result["repair_attempt"] == 1


def test_yaml_repair_rejects_secret_removal_and_unrequested_files():
    original = """app:
  containers:
    env:
      - name: api-key
        value: api-key@azurekeyvault
  kvSecrets:
    - api-key
"""

    class FakeModel:
        def __init__(self, path, content):
            self.path = path
            self.content = content

        def invoke(self, prompt):
            return ValidationRepairResponse(
                updated_files={self.path: self.content}
            )

    state = {
        "generated_files": {"values.yaml": original},
        "validation_errors": ["yamllint failed: format"],
    }
    removed_secret = """app:
  containers:
    env: []
  kvSecrets: []
"""
    with pytest.raises(ValueError, match="removed an existing Key Vault"):
        repair_validation_errors(
            state, FakeModel("values.yaml", removed_secret)
        )
    with pytest.raises(ValueError, match="outside the generated YAML set"):
        repair_validation_errors(state, FakeModel("../other.yaml", "app: {}"))
