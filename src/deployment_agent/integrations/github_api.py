"""GitHub REST API client used by repository and pull-request tools."""

from urllib.parse import quote

import requests


class GitHubAPIError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, api_url: str = "https://api.github.com") -> None:
        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _request(self, method: str, path: str, **kwargs):
        response = self.session.request(
            method, f"{self.api_url}{path}", timeout=30, **kwargs
        )
        if not response.ok:
            raise GitHubAPIError(
                f"GitHub API {method} {path} failed "
                f"({response.status_code}): {response.text[:1000]}"
            )
        if response.content:
            return response.json()
        return None

    def _get_optional(self, path: str):
        response = self.session.get(
            f"{self.api_url}{path}", timeout=30
        )
        if response.status_code == 404:
            return None
        if not response.ok:
            raise GitHubAPIError(
                f"GitHub API GET {path} failed "
                f"({response.status_code}): {response.text[:1000]}"
            )
        return response.json()

    def inspect_repository(self, owner: str, repo: str) -> tuple[str, list[dict[str, str]]]:
        quoted = f"{quote(owner, safe='')}/{quote(repo, safe='')}"
        repository = self._request("GET", f"/repos/{quoted}")
        branch = repository["default_branch"]
        branch_data = self._request(
            "GET", f"/repos/{quoted}/branches/{quote(branch, safe='')}"
        )
        tree_sha = branch_data["commit"]["commit"]["tree"]["sha"]
        tree_data = self._request(
            "GET",
            f"/repos/{quoted}/git/trees/{quote(tree_sha, safe='')}",
            params={"recursive": "1"},
        )
        if tree_data.get("truncated"):
            raise GitHubAPIError("Repository tree is too large to inspect completely")
        tree = [
            {"path": item["path"], "type": item["type"]}
            for item in tree_data.get("tree", [])
            if item.get("type") == "blob"
        ]
        return branch, tree

    def get_file(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        quoted = f"{quote(owner, safe='')}/{quote(repo, safe='')}"
        response = self.session.get(
            f"{self.api_url}/repos/{quoted}/contents/{quote(path, safe='/')}",
            params={"ref": ref},
            timeout=30,
        )
        if response.status_code == 404:
            return None
        if not response.ok:
            raise GitHubAPIError(
                f"GitHub API GET repository file failed "
                f"({response.status_code}): {response.text[:1000]}"
            )
        content = response.json()
        if content.get("encoding") != "base64":
            raise GitHubAPIError(f"Unsupported GitHub file encoding for {path}")
        import base64

        return base64.b64decode(content["content"]).decode("utf-8")

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        base: str,
        branch: str,
        files: dict[str, str],
        title: str,
        body: str,
    ) -> str:
        quoted = f"{quote(owner, safe='')}/{quote(repo, safe='')}"
        branch_ref_path = (
            f"/repos/{quoted}/git/ref/heads/{quote(branch, safe='')}"
        )
        existing_branch = self._get_optional(branch_ref_path)
        if existing_branch:
            parent_sha = existing_branch["object"]["sha"]
        else:
            base_ref = self._request(
                "GET",
                f"/repos/{quoted}/git/ref/heads/{quote(base, safe='')}",
            )
            parent_sha = base_ref["object"]["sha"]
        parent_commit = self._request(
            "GET", f"/repos/{quoted}/git/commits/{quote(parent_sha, safe='')}"
        )
        base_tree = parent_commit["tree"]["sha"]
        entries = []
        for path, content in files.items():
            blob = self._request(
                "POST",
                f"/repos/{quoted}/git/blobs",
                json={"content": content, "encoding": "utf-8"},
            )
            entries.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}
            )
        tree = self._request(
            "POST",
            f"/repos/{quoted}/git/trees",
            json={"base_tree": base_tree, "tree": entries},
        )
        commit = self._request(
            "POST",
            f"/repos/{quoted}/git/commits",
            json={
                "message": title,
                "tree": tree["sha"],
                "parents": [parent_sha],
            },
        )
        if existing_branch:
            self._request(
                "PATCH",
                f"/repos/{quoted}/git/refs/heads/{quote(branch, safe='')}",
                json={"sha": commit["sha"]},
            )
        else:
            self._request(
                "POST",
                f"/repos/{quoted}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]},
            )

        pulls = self._request(
            "GET",
            f"/repos/{quoted}/pulls",
            params={"head": f"{owner}:{branch}", "base": base, "state": "open"},
        )
        if pulls:
            pull_request = pulls[0]
            self._request(
                "PATCH",
                f"/repos/{quoted}/pulls/{pull_request['number']}",
                json={"title": title, "body": body},
            )
        else:
            pull_request = self._request(
                "POST",
                f"/repos/{quoted}/pulls",
                json={"title": title, "body": body, "head": branch, "base": base},
            )
        return pull_request["html_url"]
