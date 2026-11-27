import yaml

from deployment_agent.agent.models import HelmValuesOverrideResponse
from deployment_agent.tools.helm_values import generate_helm_repository_files
from deployment_agent.tools.helm_repository import (
    add_helm_repository_files,
)


def test_prompt_secret_name_is_added_to_existing_key_vault_pattern():
    files = generate_helm_repository_files(
        "poc-ai-agent",
        "Add this api-key into poc-ai-agent service",
    )
    values = yaml.safe_load(
        files["Application/poc/poc-ai-agent/values.yaml"]
    )
    configmap = yaml.safe_load(
        files["Application/poc/poc-ai-agent/configmap.yaml"]
    )

    assert {"name": "api-key", "value": "api-key@azurekeyvault"} in (
        values["app"]["containers"]["env"]
    )
    assert values["app"]["kvSecrets"] == ["sub-key", "api-key"]
    assert configmap["app_name"] == "poc-ai-agent"
    assert "api-key@azurekeyvault" in files[
        "Application/poc/poc-ai-agent/values.yaml"
    ]


def test_multiple_named_secrets_are_added_once():
    files = generate_helm_repository_files(
        "poc-ai-agent",
        "Add secrets named api-key and database-password to the service",
    )
    values = yaml.safe_load(
        files["Application/poc/poc-ai-agent/values.yaml"]
    )
    env = values["app"]["containers"]["env"]

    assert {"name": "api-key", "value": "api-key@azurekeyvault"} in env
    assert {
        "name": "database-password",
        "value": "database-password@azurekeyvault",
    } in env
    assert values["app"]["kvSecrets"] == [
        "sub-key",
        "api-key",
        "database-password",
    ]


def test_prompted_secret_values_are_not_copied_into_helm_files():
    files = generate_helm_repository_files(
        "poc-ai-agent",
        "Add api-key with value do-not-store-this-value",
    )

    assert all(
        "do-not-store-this-value" not in content for content in files.values()
    )


def test_secret_can_be_explicitly_removed_from_merged_values():
    existing_values = """app:
  containers:
    env:
      - name: api-key
        value: api-key@azurekeyvault
  kvSecrets:
    - api-key
"""
    files = generate_helm_repository_files(
        "poc-ai-agent",
        "Remove the secret named api-key from Helm values",
        existing_values_content=existing_values,
    )
    values = yaml.safe_load(files["Application/poc/poc-ai-agent/values.yaml"])

    assert values["app"]["containers"]["env"] == [
        {"name": "sub-key", "value": "sub-key@azurekeyvault"}
    ]
    assert values["app"]["kvSecrets"] == ["sub-key"]

    next_update = generate_helm_repository_files(
        "poc-ai-agent",
        "Increase replicas to 3",
        existing_values_content=files[
            "Application/poc/poc-ai-agent/values.yaml"
        ],
        default_values_content=existing_values,
    )
    next_values = yaml.safe_load(
        next_update["Application/poc/poc-ai-agent/values.yaml"]
    )
    assert next_values["app"]["kvSecrets"] == ["sub-key"]
    assert "api-key" not in {
        entry["name"] for entry in next_values["app"]["containers"]["env"]
    }
    assert "deployment-agent-removed-kv-secrets: api-key" in next_update[
        "Application/poc/poc-ai-agent/values.yaml"
    ]

    readded = generate_helm_repository_files(
        "poc-ai-agent",
        "Add the api-key secret to the service",
        existing_values_content=files[
            "Application/poc/poc-ai-agent/values.yaml"
        ],
        default_values_content=existing_values,
    )
    readded_content = readded["Application/poc/poc-ai-agent/values.yaml"]
    readded_values = yaml.safe_load(readded_content)
    assert "api-key" in readded_values["app"]["kvSecrets"]
    assert "deployment-agent-removed-kv-secrets" not in readded_content


def test_secret_removal_does_not_copy_an_existing_raw_value():
    files = generate_helm_repository_files(
        "poc-ai-agent",
        "Remove the secret named api-key from Helm values",
        existing_values_content="""app:
  containers:
    env:
      - name: api-key
        value: never-copy-this
  kvSecrets:
    - api-key
""",
    )

    assert all(
        "never-copy-this" not in content for content in files.values()
    )


def test_natural_language_can_set_explicit_helm_endpoints():
    class FakeValuesModel:
        def invoke(self, prompt):
            assert "never infer or invent infrastructure endpoints" in prompt
            return HelmValuesOverrideResponse(
                overrides_yaml=(
                    "app:\n"
                    "  egressSvcEntry:\n"
                    "    HTTPS:\n"
                    "      destinations:\n"
                    "        - api.example.com\n"
                    "    redis:\n"
                    "      url: cache.example.net\n"
                )
            )

    result = add_helm_repository_files(
        {
            "repo": "poc-ai-agent",
            "requirement": (
                "Set the HTTPS destination to api.example.com and Redis URL "
                "to cache.example.net"
            ),
        },
        FakeValuesModel(),
    )
    values = yaml.safe_load(
        result["external_generated_files"]["Application/poc/poc-ai-agent/values.yaml"]
    )

    assert values["app"]["egressSvcEntry"]["HTTPS"]["destinations"] == [
        "api.example.com"
    ]
    assert values["app"]["egressSvcEntry"]["redis"]["url"] == "cache.example.net"


def test_prompt_yaml_overrides_all_values_template_sections():
    files = generate_helm_repository_files(
        "poc-ai-agent",
        """Create Helm config with these values:
```yaml
app:
  replicaCount: 3
  autoscaleEnabled: false
  resources:
    limits:
      cpu: 1
      memory: 2Gi
  containers:
    port: 9090
    envCode: qa
ingress:
  enabled: false
  http: []
service:
  port: 9090
  targetPort: 9090
```
""",
    )
    values = yaml.safe_load(files["Application/poc/poc-ai-agent/values.yaml"])

    assert values["app"]["replicaCount"] == 3
    assert values["app"]["autoscaleEnabled"] is False
    assert values["app"]["autoscaleMin"] == 1
    assert values["app"]["resources"]["limits"] == {"cpu": 1, "memory": "2Gi"}
    assert values["app"]["resources"]["requests"] == {"cpu": "20m", "memory": "425Mi"}
    assert values["app"]["containers"]["port"] == 9090
    assert values["app"]["containers"]["envCode"] == "qa"
    assert values["ingress"]["enabled"] is False
    assert values["ingress"]["http"] == []
    assert values["service"]["port"] == 9090
    assert values["service"]["targetPort"] == 9090
    assert values["service"]["labels"]["app"] == "poc-ai-agent"


def test_prompt_yaml_merges_env_and_kv_secrets_by_name():
    files = generate_helm_repository_files(
        "poc-ai-agent",
        """Add the requested service settings:
```yaml
app:
  containers:
    env:
      - name: api-key
        value: api-key@azurekeyvault
  kvSecrets:
    - api-key
```
""",
    )
    values = yaml.safe_load(files["Application/poc/poc-ai-agent/values.yaml"])

    assert values["app"]["containers"]["env"] == [
        {"name": "sub-key", "value": "sub-key@azurekeyvault"},
        {"name": "api-key", "value": "api-key@azurekeyvault"},
    ]
    assert values["app"]["kvSecrets"] == ["sub-key", "api-key"]


def test_prompt_yaml_rejects_unknown_template_parameter():
    import pytest

    with pytest.raises(ValueError, match="Unknown Helm values parameter: app.unknown"):
        generate_helm_repository_files(
            "poc-ai-agent",
            "```yaml\napp:\n  unknown: true\n```",
        )


def test_prompt_yaml_rejects_raw_secret_values():
    import pytest

    with pytest.raises(ValueError, match="raw secret values are not accepted"):
        generate_helm_repository_files(
            "poc-ai-agent",
            """```yaml
app:
  containers:
    env:
      - name: api-key
        value: do-not-store-this-value
  kvSecrets:
    - api-key
```""",
        )


def test_natural_language_parameters_are_extracted_and_applied():
    class FakeValuesModel:
        def invoke(self, prompt):
            assert "values.yaml template" in prompt
            assert "increase replicas to 3" in prompt.lower()
            return HelmValuesOverrideResponse(
                overrides_yaml=(
                    "app:\n"
                    "  replicaCount: 3\n"
                    "  resources:\n"
                    "    limits:\n"
                    "      cpu: 1\n"
                    "      memory: 2Gi\n"
                )
            )

    state = {
        "repo": "poc-ai-agent",
        "requirement": "Increase replicas to 3 and set cpu limit to 1",
    }

    result = add_helm_repository_files(state, FakeValuesModel())
    values = yaml.safe_load(
        result["external_generated_files"]["Application/poc/poc-ai-agent/values.yaml"]
    )

    assert values["app"]["replicaCount"] == 3
    assert values["app"]["resources"]["limits"] == {"cpu": 1, "memory": "2Gi"}
    assert values["app"]["resources"]["requests"] == {
        "cpu": "20m",
        "memory": "425Mi",
    }


def test_spaced_autoscale_minimum_prompt_updates_the_helm_value():
    class FakeValuesModel:
        def invoke(self, prompt):
            assert "Update the auto scale min value also to 5" in prompt
            return HelmValuesOverrideResponse(
                overrides_yaml="app:\n  autoscaleMin: 5\n"
            )

    result = add_helm_repository_files(
        {
            "repo": "poc-ai-agent",
            "requirement": "Update the auto scale min value also to 5",
        },
        FakeValuesModel(),
    )
    values = yaml.safe_load(
        result["external_generated_files"]["Application/poc/poc-ai-agent/values.yaml"]
    )

    assert values["app"]["autoscaleMin"] == 5


def test_parameter_update_preserves_secrets_from_existing_shared_values():
    existing_values = """app:
  replicaCount: 3
  resources:
    limits:
      cpu: 1
  containers:
    env:
      - name: sub-key
        value: sub-key@azurekeyvault
  kvSecrets:
    - sub-key
"""
    default_values = """app:
  replicaCount: 1
  resources:
    limits:
      cpu: 500m
  containers:
    env:
      - name: sub-key
        value: sub-key@azurekeyvault
      - name: api-key
        value: api-key@azurekeyvault
      - name: database-password
        value: database-password@azurekeyvault
      - name: redis-token
        value: redis-token@azurekeyvault
  kvSecrets:
    - sub-key
    - api-key
    - database-password
    - redis-token
"""

    class FakeGitHubClient:
        def __init__(self):
            self.requested = []

        def inspect_repository(self, owner, repo):
            assert (owner, repo) == (
                "sandeepshankar1094-creator",
                "Helm-Charts",
            )
            return "trunk", []

        def get_file(self, owner, repo, path, ref):
            self.requested.append((owner, repo, path, ref))
            if ref == "agent-automation":
                return existing_values
            return default_values

    class FakeValuesModel:
        def invoke(self, prompt):
            return HelmValuesOverrideResponse(
                overrides_yaml="app:\n  replicaCount: 3\n"
            )

    client = FakeGitHubClient()
    result = add_helm_repository_files(
        {
            "repo": "poc-ai-agent",
            "requirement": "Increase replicas to 3",
        },
        FakeValuesModel(),
        client,
    )
    values = yaml.safe_load(
        result["external_generated_files"]["Application/poc/poc-ai-agent/values.yaml"]
    )

    assert values["app"]["replicaCount"] == 3
    assert values["app"]["resources"]["limits"]["cpu"] == 1
    env = values["app"]["containers"]["env"]
    for secret in ("sub-key", "api-key", "database-password", "redis-token"):
        assert {
            "name": secret,
            "value": f"{secret}@azurekeyvault",
        } in env
    assert values["app"]["kvSecrets"] == [
        "sub-key",
        "api-key",
        "database-password",
        "redis-token",
    ]
    assert any(
        "app.replicaCount differs" in warning
        for warning in result["helm_merge_warnings"]
    )
    assert client.requested == [
        (
            "sandeepshankar1094-creator",
            "Helm-Charts",
            "Application/poc/poc-ai-agent/values.yaml",
            "agent-automation",
        ),
        (
            "sandeepshankar1094-creator",
            "Helm-Charts",
            "Application/poc/poc-ai-agent/values.yaml",
            "trunk",
        ),
    ]
