import json
from pathlib import Path, PurePosixPath

from deployment_agent.agent.models import AgentState


_TEMPLATE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "templates" / "GHA-Workflows"
)


def _render_default_branch(content: str, branch: str) -> str:
    quoted_branch = json.dumps(branch)
    return (
        content.replace(
            'branches: [ "main" ]',
            f"branches: [ {quoted_branch} ]",
        )
        .replace("      - main", f"      - {quoted_branch}")
    )


def generate_ci_cd_pipeline(state: AgentState) -> AgentState:
    tree = state["tree"]
    paths = {entry["path"] for entry in tree if entry.get("type") == "blob"}
    has_angular = any(PurePosixPath(path).name == "angular.json" for path in paths)
    has_maven = any(PurePosixPath(path).name == "pom.xml" for path in paths)
    if has_angular and has_maven:
        raise ValueError(
            "Both Maven and Angular projects were found. Keep one stack per "
            "repository or select a specific workflow template."
        )
    if has_angular:
        project_type = "Angular"
    elif has_maven:
        project_type = "Maven"
    else:
        raise ValueError(
            "CI/CD workflow templates are available for Maven and Angular "
            "projects, but no matching project manifest was found."
        )

    template_directory = _TEMPLATE_DIRECTORY / project_type
    generated_files = {}
    for template_name in ("CI.yml", "CD.yml"):
        template_path = template_directory / template_name
        if not template_path.is_file():
            raise FileNotFoundError(
                f"Required {project_type} workflow template is missing: "
                f"{template_path}"
            )
        content = template_path.read_text(encoding="utf-8")
        generated_files[
            f".github/workflows/{template_name.lower()}"
        ] = _render_default_branch(content, state["default_branch"])

    return {"generated_files": generated_files}
