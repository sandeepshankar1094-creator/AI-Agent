import base64
from urllib.parse import urlsplit

import pytest
import requests

from deployment_agent.agent.models import DeploymentPlan, ToolSelection
from deployment_agent.integrations.github_api import GitHubAPIError, GitHubClient
from deployment_agent.tools.pull_requests import create_pull_request


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = ""
        self.content = b"json" if payload is not None else b""
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(
        self,
        branch_exists,
        pull_request_exists,
        existing_content="FROM alpine\n",
    ):
        self.headers = {}
        self.branch_exists = branch_exists
        self.pull_request_exists = pull_request_exists
        self.existing_content = existing_content
        self.calls = []

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def request(self, method, url, **kwargs):
        path = urlsplit(url).path
        self.calls.append((method, path, kwargs))

        if "/contents/" in path:
            if self.existing_content is None:
                return FakeResponse(404)
            encoded = base64.b64encode(
                self.existing_content.encode("utf-8")
            ).decode("ascii")
            return FakeResponse(
                200, {"encoding": "base64", "content": encoded}
            )
        if path.endswith("/git/ref/heads/agent-automation"):
            if self.branch_exists:
                return FakeResponse(200, {"object": {"sha": "branch-tip"}})
            return FakeResponse(404)
        if path.endswith("/git/ref/heads/main"):
            return FakeResponse(200, {"object": {"sha": "base-tip"}})
        if path.endswith("/git/commits/branch-tip"):
            return FakeResponse(200, {"tree": {"sha": "branch-tree"}})
        if path.endswith("/git/commits/base-tip"):
            return FakeResponse(200, {"tree": {"sha": "base-tree"}})
        if path.endswith("/git/blobs"):
            return FakeResponse(201, {"sha": "blob-sha"})
        if path.endswith("/git/trees"):
            return FakeResponse(201, {"sha": "new-tree"})
        if path.endswith("/git/commits"):
            return FakeResponse(201, {"sha": "new-commit"})
        if path.endswith("/pulls") and method == "GET":
            pull_requests = (
                [{"number": 17, "html_url": "https://github.com/acme/app/pull/17"}]
                if self.pull_request_exists
                else []
            )
            return FakeResponse(200, pull_requests)
        if path.endswith("/pulls") and method == "POST":
            return FakeResponse(
                201, {"html_url": "https://github.com/acme/app/pull/18"}
            )
        return FakeResponse(200, {})


def _client(branch_exists, pull_request_exists, existing_content="FROM alpine\n"):
    client = GitHubClient("token")
    client.session = FakeSession(
        branch_exists, pull_request_exists, existing_content
    )
    return client


def test_updates_existing_automation_branch_and_open_pr():
    client = _client(branch_exists=True, pull_request_exists=True)

    url = client.create_pull_request(
        "acme",
        "app",
        "main",
        "agent-automation",
        {"Dockerfile": "FROM scratch\n"},
        "Update Dockerfile",
        "Updated generated Dockerfile.",
    )

    calls = client.session.calls
    update_ref = next(
        call
        for call in calls
        if call[0] == "PATCH" and "/git/refs/" in call[1]
    )
    update_pr = next(
        call
        for call in calls
        if call[0] == "PATCH" and call[1].endswith("/pulls/17")
    )
    assert url == "https://github.com/acme/app/pull/17"
    assert update_ref[2]["json"] == {"sha": "new-commit"}
    assert update_pr[2]["json"]["title"] == "Update Dockerfile"
    assert not any(
        call[0] == "POST" and call[1].endswith("/git/refs") for call in calls
    )
    tree = next(
        call
        for call in calls
        if call[0] == "POST" and call[1].endswith("/git/trees")
    )
    assert tree[2]["json"]["base_tree"] == "branch-tree"


def test_creates_fixed_branch_and_pr_when_not_present():
    client = _client(branch_exists=False, pull_request_exists=False)

    url = client.create_pull_request(
        "acme",
        "app",
        "main",
        "agent-automation",
        {"Dockerfile": "FROM scratch\n"},
        "Add Dockerfile",
        "Generated Dockerfile.",
    )

    calls = client.session.calls
    create_ref = next(
        call
        for call in calls
        if call[0] == "POST" and call[1].endswith("/git/refs")
    )
    create_pr = next(
        call for call in calls if call[0] == "POST" and call[1].endswith("/pulls")
    )
    assert url == "https://github.com/acme/app/pull/18"
    assert create_ref[2]["json"]["ref"] == "refs/heads/agent-automation"
    assert create_pr[2]["json"]["head"] == "agent-automation"


def test_identical_repeated_update_returns_open_pr_without_another_commit():
    client = _client(
        branch_exists=True,
        pull_request_exists=True,
        existing_content="FROM scratch\n",
    )

    url = client.create_pull_request(
        "acme",
        "app",
        "main",
        "agent-automation",
        {"Dockerfile": "FROM scratch\n"},
        "Update Dockerfile",
        "Updated generated Dockerfile.",
    )

    assert url == "https://github.com/acme/app/pull/17"
    assert not any(
        method == "POST" and path.endswith(("/git/blobs", "/git/trees", "/git/commits"))
        for method, path, _ in client.session.calls
    )


def test_noop_without_an_open_pull_request_is_reported():
    client = _client(
        branch_exists=False,
        pull_request_exists=False,
        existing_content="FROM scratch\n",
    )

    with pytest.raises(GitHubAPIError, match="already match"):
        client.create_pull_request(
            "acme",
            "app",
            "main",
            "agent-automation",
            {"Dockerfile": "FROM scratch\n"},
            "Add Dockerfile",
            "Generated Dockerfile.",
        )


def test_transient_get_failure_is_retried(monkeypatch):
    class FlakySession:
        headers = {}

        def __init__(self):
            self.calls = 0

        def request(self, method, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(503)
            return FakeResponse(200, {"ready": True})

    client = GitHubClient("token")
    client.session = FlakySession()
    monkeypatch.setattr("deployment_agent.integrations.github_api.time.sleep", lambda _: None)

    assert client._request("GET", "/health") == {"ready": True}
    assert client.session.calls == 2


def test_non_idempotent_post_is_not_retried_after_connection_failure():
    class FailingSession:
        headers = {}

        def __init__(self):
            self.calls = 0

        def request(self, method, url, **kwargs):
            self.calls += 1
            raise requests.ConnectionError("connection interrupted")

    client = GitHubClient("token")
    client.session = FailingSession()

    with pytest.raises(GitHubAPIError, match="connection interrupted"):
        client._request("POST", "/repos/acme/app/git/blobs", json={"content": "x"})
    assert client.session.calls == 1


def test_generated_paths_must_be_repository_relative():
    client = _client(branch_exists=False, pull_request_exists=False)

    with pytest.raises(GitHubAPIError, match="Invalid repository-relative"):
        client.create_pull_request(
            "acme",
            "app",
            "main",
            "agent-automation",
            {"../outside.txt": "not allowed"},
            "Add file",
            "Generated file.",
        )


def test_pr_tool_always_uses_the_shared_branch():
    class CaptureClient:
        def create_pull_request(self, *args):
            self.args = args
            return "https://github.com/acme/app/pull/18"

    client = CaptureClient()
    state = {
        "owner": "acme",
        "repo": "app",
        "default_branch": "main",
        "plan": DeploymentPlan(application_name="app", create_dockerfile=True),
        "tool_selection": ToolSelection(
            selected_tool="create_dockerfile_only",
            normalized_request="create a Dockerfile",
        ),
        "generated_files": {"Dockerfile": "FROM scratch\n"},
    }

    create_pull_request(state, client)

    assert client.args[3] == "agent-automation"


def test_ci_cd_pr_skips_validation_and_uses_shared_branch():
    class CaptureClient:
        def create_pull_request(self, *args):
            self.args = args
            return "https://github.com/acme/app/pull/18"

    client = CaptureClient()
    state = {
        "owner": "acme",
        "repo": "app",
        "default_branch": "main",
        "tool_selection": ToolSelection(
            selected_tool="create_ci_cd_pipeline",
            normalized_request="Create a CI/CD pipeline",
        ),
        "generated_files": {
            ".github/workflows/ci.yml": "name: CI\n",
            ".github/workflows/cd.yml": "name: CD\n",
        },
    }

    create_pull_request(state, client)

    assert client.args[3] == "agent-automation"
    assert client.args[5] == "Add CI/CD workflows for app"
    assert "Validation was skipped" in client.args[6]


def test_helm_chart_request_creates_pr_in_shared_repository_only():
    class CaptureClient:
        def __init__(self):
            self.pull_requests = []

        def inspect_repository(self, owner, repo):
            self.target = (owner, repo)
            return "main", []

        def create_pull_request(self, *args):
            self.pull_requests.append(args)
            return f"https://github.com/{args[0]}/{args[1]}/pull/1"

    client = CaptureClient()
    state = {
        "owner": "acme",
        "repo": "java-springboot",
        "default_branch": "main",
        "tool_selection": ToolSelection(
            selected_tool="create_helm_chart_only",
            normalized_request="Create Helm charts",
        ),
        "external_generated_files": {
            "Application/java/java-springboot/configmap.yaml": "app_name: java-springboot\n",
            "Application/java/java-springboot/values.yaml": "app: {}\n",
        },
    }

    result = create_pull_request(state, client)

    assert client.target == ("sandeepshankar1094-creator", "Helm-Charts")
    assert len(client.pull_requests) == 1
    assert client.pull_requests[0][3] == "agent-automation"
    assert client.pull_requests[0][4] == state["external_generated_files"]
    assert result["pull_request_url"] == (
        "https://github.com/sandeepshankar1094-creator/Helm-Charts/pull/1"
    )


def test_cd_request_opens_source_and_shared_chart_repository_prs():
    class CaptureClient:
        def __init__(self):
            self.pull_requests = []

        def inspect_repository(self, owner, repo):
            return "main", []

        def create_pull_request(self, *args):
            self.pull_requests.append(args)
            return f"https://github.com/{args[0]}/{args[1]}/pull/{len(self.pull_requests)}"

    client = CaptureClient()
    state = {
        "owner": "acme",
        "repo": "java-springboot",
        "default_branch": "main",
        "tool_selection": ToolSelection(
            selected_tool="create_ci_cd_pipeline",
            normalized_request="Create CD pipeline",
        ),
        "generated_files": {".github/workflows/cd.yml": "name: Deploy\n"},
        "external_generated_files": {
            "Application/java/java-springboot/configmap.yaml": "app_name: java-springboot\n",
            "Application/java/java-springboot/values.yaml": "app: {}\n",
        },
    }

    result = create_pull_request(state, client)

    assert len(client.pull_requests) == 2
    assert (client.pull_requests[0][0], client.pull_requests[0][1]) == (
        "acme",
        "java-springboot",
    )
    assert (client.pull_requests[1][0], client.pull_requests[1][1]) == (
        "sandeepshankar1094-creator",
        "Helm-Charts",
    )
    assert result["pull_request_urls"] == [
        "https://github.com/acme/java-springboot/pull/1",
        "https://github.com/sandeepshankar1094-creator/Helm-Charts/pull/2",
    ]


def test_publish_skips_repository_with_no_preview_changes():
    class CaptureClient:
        def __init__(self):
            self.pull_requests = []

        def inspect_repository(self, owner, repo):
            return "main", []

        def create_pull_request(self, *args):
            self.pull_requests.append(args)
            return f"https://github.com/{args[0]}/{args[1]}/pull/1"

    client = CaptureClient()
    state = {
        "owner": "acme",
        "repo": "java-springboot",
        "default_branch": "main",
        "tool_selection": ToolSelection(
            selected_tool="create_ci_cd_pipeline",
            normalized_request="Create CD pipeline",
        ),
        "generated_files": {".github/workflows/cd.yml": "name: Deploy\n"},
        "external_generated_files": {
            "Application/java/java-springboot/values.yaml": "app: {}\n"
        },
        "preview_changes": [
            {
                "repository": "sandeepshankar1094-creator/Helm-Charts",
                "path": "Application/java/java-springboot/values.yaml",
                "diff": "+app: {}\n",
            }
        ],
    }

    result = create_pull_request(state, client)

    assert len(client.pull_requests) == 1
    assert client.pull_requests[0][1] == "Helm-Charts"
    assert result["pull_request_urls"] == [
        "https://github.com/sandeepshankar1094-creator/Helm-Charts/pull/1"
    ]
