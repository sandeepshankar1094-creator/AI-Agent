"""Pure-Python GitHub Actions and Helm file generation."""

from pathlib import PurePosixPath
import re
import shlex

import yaml

from deployment_agent.agent.models import DeploymentPlan


class _IndentedSafeDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)

    def represent_str(self, value):
        style = "|" if "\n" in value else None
        return self.represent_scalar("tag:yaml.org,2002:str", value, style=style)


def _dump_yaml(value: dict) -> str:
    _IndentedSafeDumper.add_representer(str, _IndentedSafeDumper.represent_str)
    return yaml.dump(
        value,
        Dumper=_IndentedSafeDumper,
        sort_keys=False,
        explicit_start=True,
        indent=2,
    )


def _validate_relative_path(value: str, label: str, allow_dot: bool = False) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or (not path.parts and not allow_dot)
        or any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in path.parts)
    ):
        raise ValueError(f"{label} must be a safe repository-relative path")
    return path.as_posix()


def generate_files(
    plan: DeploymentPlan, owner: str, repo: str, default_branch: str = "main"
) -> dict[str, str]:
    chart_path = _validate_relative_path(plan.chart_path, "chart_path")
    workflow_path = _validate_relative_path(plan.workflow_path, "workflow_path")
    context = _validate_relative_path(plan.build_context, "build_context", allow_dot=True)
    dockerfile = _validate_relative_path(plan.dockerfile_path, "dockerfile_path")
    namespace = plan.namespace
    image = f"ghcr.io/{owner}/{repo}".lower()

    workflow = {
        "name": "Build and deploy",
        "on": {
            "push": {"branches": [default_branch]},
            "workflow_dispatch": {},
        },
        "permissions": {
            "contents": "read",
            "packages": "write",
        },
        "jobs": {
            "build-and-deploy": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {
                        "name": "Set up Docker Buildx",
                        "uses": "docker/setup-buildx-action@v3",
                    },
                    {
                        "name": "Log in to GitHub Container Registry",
                        "uses": "docker/login-action@v3",
                        "with": {
                            "registry": "ghcr.io",
                            "username": "${{ github.actor }}",
                            "password": "${{ secrets.GITHUB_TOKEN }}",
                        },
                    },
                    {
                        "name": "Set image name",
                        "run": (
                            'image="ghcr.io/${GITHUB_REPOSITORY,,}"\n'
                            'echo "IMAGE_NAME=$image" >> "$GITHUB_ENV"'
                        ),
                    },
                    {
                        "name": "Build and push image",
                        "uses": "docker/build-push-action@v6",
                        "with": {
                            "context": context,
                            "file": dockerfile,
                            "push": True,
                            "tags": "${{ env.IMAGE_NAME }}:${{ github.sha }}",
                        },
                    },
                    {
                        "name": "Set up Helm",
                        "uses": "azure/setup-helm@v4",
                    },
                    {
                        "name": "Configure Kubernetes access",
                        "env": {"KUBE_CONFIG": "${{ secrets.KUBE_CONFIG }}"},
                        "run": (
                            "mkdir -p \"$HOME/.kube\"\n"
                            "echo \"$KUBE_CONFIG\" | base64 -d > \"$HOME/.kube/config\"\n"
                            "chmod 600 \"$HOME/.kube/config\""
                        ),
                    },
                    {
                        "name": "Deploy with Helm",
                        "run": (
                            "helm upgrade --install "
                            f"{shlex.quote(plan.application_name)} {shlex.quote(chart_path)} \\\n"
                            f"  --namespace {shlex.quote(namespace)} --create-namespace \\\n"
                            '  --set image.repository="$IMAGE_NAME" \\\n'
                            "  --set image.tag=${GITHUB_SHA}"
                        ),
                    },
                ],
            }
        },
    }

    chart_metadata = {
        "apiVersion": "v2",
        "name": plan.application_name,
        "description": f"Helm chart for {plan.application_name}",
        "type": "application",
        "version": "0.1.0",
        "appVersion": "1.0.0",
    }
    values = {
        "replicaCount": plan.replicas,
        "image": {"repository": image, "tag": "latest", "pullPolicy": "IfNotPresent"},
        "service": {"type": "ClusterIP", "port": plan.container_port},
    }

    deployment_template = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
  namespace: {{ .Release.Namespace }}
  labels:
    app.kubernetes.io/name: {{ .Chart.Name }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ .Chart.Name }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ .Chart.Name }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: {{ .Values.service.port }}
              protocol: TCP
"""
    service_template = """apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
  namespace: {{ .Release.Namespace }}
  labels:
    app.kubernetes.io/name: {{ .Chart.Name }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    app.kubernetes.io/name: {{ .Chart.Name }}
"""

    generated = {
        workflow_path: _dump_yaml(workflow),
        f"{chart_path}/Chart.yaml": _dump_yaml(chart_metadata),
        f"{chart_path}/values.yaml": _dump_yaml(values),
        f"{chart_path}/templates/deployment.yaml": deployment_template,
        f"{chart_path}/templates/service.yaml": service_template,
    }
    if len(generated) != 5 or any(
        other.startswith(f"{path}/")
        for path in generated
        for other in generated
        if path != other
    ):
        raise ValueError("Generated workflow and chart paths must not overlap")
    return generated
