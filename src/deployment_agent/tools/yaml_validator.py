import shutil
import subprocess
import sysconfig
import tempfile
from pathlib import Path

import yaml

from deployment_agent.agent.models import DeploymentPlan


def _run(command: list[str], cwd: Path) -> str | None:
    result = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, check=False, timeout=120
    )
    if result.returncode:
        return (result.stdout + result.stderr).strip() or f"Command failed: {command[0]}"
    return None


def validate_files(
    files: dict[str, str],
    plan: DeploymentPlan,
    source_files: dict[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="deployment-agent-") as directory:
        root = Path(directory)
        all_files = {**(source_files or {}), **files}
        for relative, content in all_files.items():
            target = root.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))

        for relative, content in files.items():
            if relative.endswith((".yaml", ".yml")) and "/templates/" not in relative:
                try:
                    yaml.safe_load(content)
                except yaml.YAMLError as exc:
                    errors.append(f"{relative}: invalid YAML: {exc}")

        yamllint = shutil.which("yamllint")
        if not yamllint:
            scripts = Path(sysconfig.get_path("scripts"))
            for name in ("yamllint.exe", "yamllint"):
                candidate = scripts / name
                if candidate.is_file():
                    yamllint = str(candidate)
                    break
        if not yamllint:
            errors.append("yamllint is required but was not found on PATH")
        else:
            lint_targets = [
                str(root.joinpath(*relative.split("/")))
                for relative in files
                if relative.endswith((".yaml", ".yml")) and "/templates/" not in relative
            ]
            if lint_targets:
                lint_error = _run([yamllint, "-s", *lint_targets], root)
                if lint_error:
                    errors.append(f"yamllint failed:\n{lint_error}")

        helm = shutil.which("helm")
        if not helm:
            errors.append("helm is required but was not found on PATH")
        else:
            chart = root.joinpath(*plan.chart_path.split("/"))
            helm_error = _run([helm, "template", plan.application_name, str(chart)], root)
            if helm_error:
                errors.append(f"helm template failed:\n{helm_error}")

        dockerfile = root.joinpath(*plan.dockerfile_path.split("/"))
        if not dockerfile.is_file():
            errors.append(f"Dockerfile {plan.dockerfile_path} was not found in the repository")
        else:
            docker = shutil.which("docker")
            if not docker:
                errors.append("Docker is required to validate the repository Dockerfile")
            else:
                docker_error = _run(
                    [
                        docker,
                        "build",
                        "--check",
                        "--file",
                        str(dockerfile),
                        str(root.joinpath(*plan.build_context.split("/"))),
                    ],
                    root,
                )
                if docker_error:
                    errors.append(f"docker build --check failed:\n{docker_error}")
    return errors
