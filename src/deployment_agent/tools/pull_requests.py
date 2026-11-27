import difflib
import re

import yaml

from deployment_agent.agent.models import AgentState, PreviewChange
from deployment_agent.integrations.github_api import GitHubAPIError, GitHubClient
from deployment_agent.tools.helm_repository import create_helm_repository_pull_request


AUTOMATION_BRANCH = "agent-automation"
_SECRET_FIELD = re.compile(r"(?:key|token|password|secret)", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^(\s*(?:(?:ENV|ARG|export)\s+)?"
    r"[A-Z0-9_.-]*(?:key|token|password|secret)[A-Z0-9_.-]*\s*[:=]\s*)(.+)$"
)


def _preview_content(path: str, content: str) -> str:
    if not path.endswith((".yaml", ".yml")):
        def redact_assignment(match: re.Match) -> str:
            value = match.group(2).strip().strip("\"'")
            if "@azurekeyvault" in value or "secrets." in value:
                return match.group(0)
            return f'{match.group(1)}"[REDACTED]"'

        return _SECRET_ASSIGNMENT.sub(redact_assignment, content)
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return "[Content hidden because YAML could not be safely redacted.]\n"
    app = data.get("app", {}) if isinstance(data, dict) else {}
    kv_secrets = app.get("kvSecrets", []) if isinstance(app, dict) else []
    secret_names = (
        {name.lower() for name in kv_secrets if isinstance(name, str)}
        if isinstance(kv_secrets, list)
        else set()
    )
    lines = []
    env_indent = None
    secret_env_entry = False
    for line in content.splitlines(keepends=True):
        indentation = len(line) - len(line.lstrip(" "))
        stripped = line.lstrip(" ")
        if re.match(r"env\s*:", stripped):
            env_indent = indentation
            secret_env_entry = False
        elif (
            env_indent is not None
            and stripped.strip()
            and not stripped.startswith("#")
        ):
            if indentation <= env_indent:
                env_indent = None
                secret_env_entry = False
            else:
                name_match = re.match(r"-\s+name:\s*[\"']?([^\"'#\s]+)", stripped)
                if name_match:
                    name = name_match.group(1)
                    secret_env_entry = (
                        name.lower() in secret_names or bool(_SECRET_FIELD.search(name))
                    )
                elif re.match(r"-\s+", stripped):
                    secret_env_entry = False

        if secret_env_entry:
            value_match = re.match(
                r"^(\s*value:\s*)(.*?)(\s+#.*)?(\r?\n)?$", line
            )
            if value_match:
                value = value_match.group(2).strip().strip("\"'")
                if "@azurekeyvault" not in value and "secrets." not in value:
                    line = (
                        value_match.group(1)
                        + '"[REDACTED]"'
                        + (value_match.group(3) or "")
                        + (value_match.group(4) or "")
                    )

        def redact_assignment(match: re.Match) -> str:
            value = match.group(2).strip().strip("\"'")
            if "@azurekeyvault" in value or "secrets." in value:
                return match.group(0)
            return f'{match.group(1)}"[REDACTED]"'

        lines.append(_SECRET_ASSIGNMENT.sub(redact_assignment, line))

    return "".join(lines)


def prepare_pull_request_preview(
    state: AgentState, client: GitHubClient
) -> AgentState:
    changes: list[PreviewChange] = []
    targets = []
    if state.get("generated_files"):
        targets.append(
            (
                state["owner"],
                state["repo"],
                state["default_branch"],
                state["generated_files"],
            )
        )
    if state.get("external_generated_files"):
        default_branch, _ = client.inspect_repository(
            "sandeepshankar1094-creator", "Helm-Charts"
        )
        targets.append(
            (
                "sandeepshankar1094-creator",
                "Helm-Charts",
                default_branch,
                state["external_generated_files"],
            )
        )

    for owner, repo, default_branch, files in targets:
        repository = f"{owner}/{repo}"
        for path, content in files.items():
            existing = client.get_file(owner, repo, path, AUTOMATION_BRANCH)
            if existing is None:
                existing = client.get_file(owner, repo, path, default_branch)
            if existing == content:
                continue
            before = _preview_content(path, existing) if existing is not None else ""
            after = _preview_content(path, content)
            diff = difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{repository}/{path}" if existing is not None else "/dev/null",
                tofile=f"b/{repository}/{path}",
            )
            changes.append(
                {
                    "repository": repository,
                    "path": path,
                    "diff": "".join(diff),
                }
            )
    return {"preview_changes": changes}


def create_pull_request(state: AgentState, client: GitHubClient) -> AgentState:
    selection = state.get("tool_selection")
    selected_tool = selection.selected_tool if selection else None
    plan = state.get("plan")
    application_name = plan.application_name if plan else state["repo"]
    if selected_tool == "create_dockerfile_only":
        title = f"Add Dockerfile for {state['repo']}"
        body = (
            "Generated by Deployment Agent.\n\n"
            "- Adds a Dockerfile using the detected project template.\n"
            "- Validation was skipped as requested."
        )
    elif selected_tool == "create_ci_cd_pipeline":
        title = f"Add CI/CD workflows for {state['repo']}"
        body = (
            "Generated by Deployment Agent.\n\n"
            "- Adds the repository's matching GitHub Actions CI and CD templates.\n"
            "- Validation was skipped as requested."
        )
    elif selected_tool == "create_helm_chart_only":
        title = f"Add Helm chart for {state['repo']}"
        body = (
            "Generated by Deployment Agent.\n\n"
            "- Adds Helm chart files for the application.\n"
            "- Validation was skipped as requested."
        )
    else:
        title = f"Add deployment configuration for {application_name}"
        body = (
            "Generated by Deployment Agent.\n\n"
            "- Adds a GitHub Actions build/deploy workflow.\n"
            "- Adds a Helm chart.\n"
            "- YAML, Helm, and available Dockerfile checks passed.\n\n"
            "Before merging, configure the `KUBE_CONFIG` repository secret."
        )
    urls = []
    preview_repositories = {
        change["repository"] for change in state.get("preview_changes", [])
    }
    has_preview_data = "preview_changes" in state
    source_repository = f"{state['owner']}/{state['repo']}"
    if selected_tool != "create_helm_chart_only" and (
        not has_preview_data or source_repository in preview_repositories
    ):
        urls.append(
            client.create_pull_request(
                state["owner"],
                state["repo"],
                state["default_branch"],
                AUTOMATION_BRANCH,
                state["generated_files"],
                title,
                body,
            )
        )
    helm_repository = "sandeepshankar1094-creator/Helm-Charts"
    if state.get("external_generated_files") and (
        not has_preview_data or helm_repository in preview_repositories
    ):
        try:
            urls.append(create_helm_repository_pull_request(state, client))
        except (GitHubAPIError, ValueError) as exc:
            if urls:
                raise GitHubAPIError(
                    "Some pull requests were created, but the Helm-Charts "
                    f"repository update failed. Created: {', '.join(urls)}. "
                    f"Cause: {exc}"
                ) from exc
            raise
    if not urls:
        raise ValueError("No generated files were available for a pull request")
    return {"pull_request_url": urls[0], "pull_request_urls": urls}


def publish_preview(state: AgentState, client: GitHubClient) -> AgentState:
    if state.get("validation_errors"):
        raise ValueError("Cannot publish changes while validation errors remain")
    if not state.get("preview_changes"):
        raise ValueError("The preview contains no changes to publish")
    return create_pull_request(state, client)
