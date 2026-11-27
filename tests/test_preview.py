from deployment_agent.tools.pull_requests import prepare_pull_request_preview


def test_preview_shows_unified_diff_and_redacts_existing_secret_values():
    existing = """app:
  replicaCount: 1
  containers:
    env:
      - name: api-key
        value: do-not-display-this
  kvSecrets:
    - api-key
# deployment-agent-removed-kv-secrets: legacy-token
"""
    generated = """app:
  replicaCount: 3
  containers:
    env:
      - name: api-key
        value: api-key@azurekeyvault
  kvSecrets:
    - api-key
"""

    class FakeGitHubClient:
        def get_file(self, owner, repo, path, ref):
            if ref == "agent-automation":
                return existing
            raise AssertionError("The automation branch already contains the file")

    result = prepare_pull_request_preview(
        {
            "owner": "acme",
            "repo": "service",
            "default_branch": "main",
            "generated_files": {"values.yaml": generated},
        },
        FakeGitHubClient(),
    )

    assert len(result["preview_changes"]) == 1
    change = result["preview_changes"][0]
    assert change["repository"] == "acme/service"
    assert change["path"] == "values.yaml"
    assert "-  replicaCount: 1" in change["diff"]
    assert "+  replicaCount: 3" in change["diff"]
    assert "do-not-display-this" not in change["diff"]
    assert "api-key@azurekeyvault" in change["diff"]
    assert "deployment-agent-removed-kv-secrets: legacy-token" in change["diff"]


def test_preview_omits_files_that_already_match():
    content = "name: example\n"

    class FakeGitHubClient:
        def get_file(self, owner, repo, path, ref):
            return content

    result = prepare_pull_request_preview(
        {
            "owner": "acme",
            "repo": "service",
            "default_branch": "main",
            "generated_files": {"workflow.yml": content},
        },
        FakeGitHubClient(),
    )

    assert result["preview_changes"] == []
