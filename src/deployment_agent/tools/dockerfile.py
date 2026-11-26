import json
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from deployment_agent.agent.models import DeploymentPlan
from deployment_agent.integrations.github_api import GitHubClient


_TEMPLATE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "templates" / "Dockerfiles"
)


def _safe_repository_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or ":" in value
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise ValueError(f"Unsafe repository path: {value}")
    return path.as_posix()


def project_root(plan: DeploymentPlan, tree: list[dict[str, str]]) -> str:
    files = {entry["path"] for entry in tree if entry.get("type") == "blob"}
    manifest_paths = [
        path
        for path in files
        if PurePosixPath(path).name in {"pom.xml", "package.json", "angular.json"}
    ]
    angular_roots = sorted(
        PurePosixPath(path).parent.as_posix()
        for path in manifest_paths
        if PurePosixPath(path).name == "angular.json"
    )
    angular_roots = [root for root in angular_roots if root != "."]

    requested_context = plan.build_context
    if requested_context != ".":
        context = _safe_repository_path(requested_context)
        manifests_in_context = [
            path
            for path in manifest_paths
            if path.startswith(f"{context}/")
        ]
        if not manifests_in_context:
            raise ValueError(
                f"No Maven, Node, or Angular project manifest was found in {context}"
            )
        angular_in_context = [
            root
            for root in angular_roots
            if root.startswith(f"{context}/") or root == context
        ]
        if len(angular_in_context) == 1:
            return angular_in_context[0]
        if len(angular_in_context) > 1:
            raise ValueError(
                "Multiple Angular projects were found under "
                f"{context}. Specify the target project directory: "
                f"{', '.join(angular_in_context)}"
            )
        if any(
            PurePosixPath(path).parent.as_posix() == context
            and PurePosixPath(path).name in {"pom.xml", "package.json"}
            for path in manifests_in_context
        ):
            return context
        roots_in_context = sorted(
            {
                PurePosixPath(path).parent.as_posix()
                for path in manifests_in_context
                if PurePosixPath(path).parent.as_posix() != "."
            }
        )
        if len(roots_in_context) == 1:
            return roots_in_context[0]
        raise ValueError(
            f"Multiple project roots were found in {context}. Specify the target "
            f"project directory: {', '.join(roots_in_context)}"
        )

    if len(angular_roots) == 1:
        return angular_roots[0]
    if len(angular_roots) > 1:
        raise ValueError(
            "Multiple Angular projects were found. Specify the target project "
            f"directory in your prompt: {', '.join(angular_roots)}"
        )

    roots = {
        PurePosixPath(path).parent.as_posix()
        for path in manifest_paths
        if PurePosixPath(path).name in {"pom.xml", "package.json"}
    }
    roots.discard(".")

    if "." in {
        PurePosixPath(path).parent.as_posix() for path in manifest_paths
        if PurePosixPath(path).name in {"pom.xml", "package.json"}
    }:
        return "."
    if not roots:
        raise ValueError(
            "No Maven pom.xml, Node package.json, or Angular angular.json "
            "was found in the repository"
        )

    shallowest_depth = min(len(PurePosixPath(root).parts) for root in roots)
    candidates = sorted(
        root for root in roots if len(PurePosixPath(root).parts) == shallowest_depth
    )
    if len(candidates) != 1:
        raise ValueError(
            "Multiple application roots were found. Specify the target project "
            f"directory in your prompt: {', '.join(candidates)}"
        )
    return candidates[0]


def _read_required_file(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str,
    branch: str,
) -> str:
    content = client.get_file(owner, repo, path, branch)
    if content is None:
        raise ValueError(f"Required project file {path} was not found")
    return content


def _angular_output_path(
    angular_config: str, package_manifest: str
) -> str:
    try:
        config = json.loads(angular_config)
        package = json.loads(package_manifest)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse Angular/Node project metadata: {exc}") from exc

    if not isinstance(config, dict) or not isinstance(package, dict):
        raise ValueError("Angular and package manifests must contain JSON objects")

    project_name = config.get("defaultProject")
    projects = config.get("projects", {})
    if not isinstance(projects, dict) or not projects:
        raise ValueError("angular.json does not define any projects")
    if project_name not in projects:
        project_name = next(iter(projects))
    project = projects[project_name]
    if not isinstance(project, dict):
        raise ValueError("Angular project configuration is invalid")

    targets = project.get("architect", project.get("targets", {}))
    if not isinstance(targets, dict):
        raise ValueError("Angular build configuration is invalid")
    build = targets.get("build", {})
    options = build.get("options", {}) if isinstance(build, dict) else {}
    output_path = options.get("outputPath")
    if isinstance(output_path, dict):
        output_path = output_path.get("base")
        if output_path and options.get("outputPath", {}).get("browser"):
            output_path = f"{output_path}/{options['outputPath']['browser']}"
    if not isinstance(output_path, str) or not output_path:
        package_name = package.get("name") or project_name
        output_path = f"dist/{package_name}/browser"

    safe_path = _safe_repository_path(output_path)
    return safe_path


def _render_angular_template(
    template: str,
    output_path: str,
    has_npm_lock: bool,
) -> str:
    rendered = template.replace("{{ANGULAR_OUTPUT_PATH}}", output_path)
    if not has_npm_lock:
        rendered = rendered.replace("RUN npm ci", "RUN npm install")
    if "{{" in rendered:
        raise ValueError("Angular Dockerfile template has unresolved placeholders")
    return rendered


def _render_node_server_template(
    template: str,
    package_manifest: dict,
    container_port: int,
    has_npm_lock: bool,
) -> str:
    scripts = package_manifest.get("scripts", {})
    if not isinstance(scripts, dict) or "start" not in scripts:
        raise ValueError(
            "Node package.json must define a start script for the NodeServer template"
        )
    build_step = "RUN npm run build" if "build" in scripts else "# No build step"
    rendered = (
        template.replace(
            "{{INSTALL_COMMAND}}", "npm ci" if has_npm_lock else "npm install"
        )
        .replace("{{BUILD_STEP}}", build_step)
        .replace("{{CONTAINER_PORT}}", str(container_port))
    )
    if "{{" in rendered:
        raise ValueError("NodeServer Dockerfile template has unresolved placeholders")
    return rendered


def generate_project_dockerfile(
    plan: DeploymentPlan,
    tree: list[dict[str, str]],
    owner: str,
    repo: str,
    branch: str,
    client: GitHubClient,
) -> tuple[DeploymentPlan, dict[str, str]]:
    root = project_root(plan, tree)
    files = {entry["path"] for entry in tree if entry.get("type") == "blob"}
    root_path = "" if root == "." else f"{root}/"
    maven_manifest = f"{root_path}pom.xml"
    package_manifest = f"{root_path}package.json"
    angular_manifest = f"{root_path}angular.json"

    if maven_manifest in files:
        pom_content = _read_required_file(
            client, owner, repo, maven_manifest, branch
        )
        try:
            ElementTree.fromstring(pom_content)
        except ElementTree.ParseError as exc:
            raise ValueError(f"Could not parse Maven project file {maven_manifest}") from exc
        template_name = "Maven"
        dockerfile_content = (_TEMPLATE_DIRECTORY / template_name).read_text(
            encoding="utf-8"
        )
        dockerfile_content = dockerfile_content.replace(
            "EXPOSE 8080", f"EXPOSE {plan.container_port}"
        )
    elif package_manifest in files:
        package_content = _read_required_file(
            client, owner, repo, package_manifest, branch
        )
        try:
            package_data = json.loads(package_content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse Node project file {package_manifest}") from exc
        if not isinstance(package_data, dict):
            raise ValueError(f"{package_manifest} must contain a JSON object")
        has_npm_lock = (
            f"{root_path}package-lock.json" in files
            or f"{root_path}npm-shrinkwrap.json" in files
        )
        if angular_manifest in files:
            scripts = package_data.get("scripts", {})
            if not isinstance(scripts, dict) or "build" not in scripts:
                raise ValueError("Angular package.json must define a build script")
            angular_config = _read_required_file(
                client, owner, repo, angular_manifest, branch
            )
            output_path = _angular_output_path(angular_config, package_content)
            dockerfile_content = (
                (_TEMPLATE_DIRECTORY / "Node").read_text(encoding="utf-8")
            )
            dockerfile_content = _render_angular_template(
                dockerfile_content, output_path, has_npm_lock
            )
        else:
            dockerfile_content = (
                (_TEMPLATE_DIRECTORY / "NodeServer").read_text(encoding="utf-8")
            )
            dockerfile_content = _render_node_server_template(
                dockerfile_content,
                package_data,
                plan.container_port,
                has_npm_lock,
            )
    else:
        raise ValueError(
            "Dockerfile generation currently supports Maven and Node projects "
            "with pom.xml or package.json."
        )

    dockerfile_path = (
        f"{root_path}{plan.dockerfile_path}"
        if root_path
        else plan.dockerfile_path
    )
    dockerfile_path = _safe_repository_path(dockerfile_path)
    updated_plan = plan.model_copy(
        update={
            "build_context": root,
            "dockerfile_path": dockerfile_path,
        }
    )
    return updated_plan, {dockerfile_path: dockerfile_content}
