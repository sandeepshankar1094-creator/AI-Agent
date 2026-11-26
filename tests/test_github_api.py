from urllib.parse import urlsplit

from deployment_agent.agent.models import DeploymentPlan, ToolSelection
from deployment_agent.integrations.github_api import GitHubClient
from deployment_agent.tools.github import create_pull_request


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = ""
        self.content = b"json" if payload is not None else b""
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, branch_exists, pull_request_exists):
        self.headers = {}
        self.branch_exists = branch_exists
        self.pull_request_exists = pull_request_exists
        self.calls = []

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def request(self, method, url, **kwargs):
        path = urlsplit(url).path
        self.calls.append((method, path, kwargs))

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


def _client(branch_exists, pull_request_exists):
    client = GitHubClient("token")
    client.session = FakeSession(branch_exists, pull_request_exists)
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
