"""Shared state and request models for the LangGraph agent."""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class DeploymentPlan(BaseModel):
    application_name: str = Field(
        min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$"
    )
    build_context: str = Field(default=".", min_length=1, max_length=255)
    dockerfile_path: str = Field(default="Dockerfile", min_length=1, max_length=255)
    create_dockerfile: bool = False
    container_port: int = Field(default=8080, ge=1, le=65535)
    replicas: int = Field(default=1, ge=1, le=100)
    namespace: str = Field(
        default="default",
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    chart_path: str = Field(default="deploy/chart", min_length=1, max_length=255)
    workflow_path: str = Field(
        default=".github/workflows/deploy.yml", min_length=1, max_length=255
    )


class ToolSelection(BaseModel):
    selected_tool: Literal[
        "list_repository_files",
        "answer_repository_question",
        "read_repository_files",
        "create_dockerfile_only",
        "create_ci_cd_pipeline",
        "generate_deployment_configuration",
    ]
    normalized_request: str = Field(min_length=1)
    file_paths: list[str] = Field(default_factory=list, max_length=3)


class AgentState(TypedDict, total=False):
    repository: str
    requirement: str
    owner: str
    repo: str
    default_branch: str
    tree: list[dict[str, str]]
    tool_selection: ToolSelection
    normalized_requirement: str
    response: str
    requirement_summary: str
    plan: DeploymentPlan
    source_files: dict[str, str]
    generated_files: dict[str, str]
    validation_errors: list[str]
    validation_analysis: str
    pull_request_url: str
    error: str
