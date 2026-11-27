import os
import re

from langchain_openai import AzureChatOpenAI
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from deployment_agent.integrations.github_api import GitHubClient
from deployment_agent.agent.models import (
    AgentState,
    DeploymentPlan,
    HelmValuesOverrideResponse,
    ToolSelection,
    ValidationRepairResponse,
)
from deployment_agent.agent.routing import route_request
from deployment_agent.tools.deployment import (
    generate_deployment_files,
    generate_dockerfile_only,
    generate_helm_chart_only,
    identify_deployment_requirements,
    summarize_requirement,
)
from deployment_agent.tools.gha_workflows import generate_ci_cd_pipeline
from deployment_agent.tools.github import (
    inspect_repository,
)
from deployment_agent.tools.pull_requests import (
    prepare_pull_request_preview,
    publish_preview,
)
from deployment_agent.tools.repository import (
    answer_repository_question,
    list_repository_files,
    read_repository_files,
)
from deployment_agent.tools.validation import (
    analyze_validation_errors,
    repair_validation_errors,
    should_attempt_validation_repair,
    validate_deployment_files,
)


def _chat_model() -> AzureChatOpenAI:
    required = (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing Azure OpenAI environment variables: {', '.join(missing)}")
    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        temperature=0,
    )


def _github_client() -> GitHubClient:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    return GitHubClient(token, os.getenv("GITHUB_API_URL", "https://api.github.com"))


def build_graph():
    load_dotenv()
    model = _chat_model()
    tool_selector = model.with_structured_output(ToolSelection)
    structured_model = model.with_structured_output(DeploymentPlan)
    helm_values_model = model.with_structured_output(HelmValuesOverrideResponse)
    validation_repair_model = model.with_structured_output(ValidationRepairResponse)

    graph = StateGraph(AgentState)
    graph.add_node("select_tool", lambda state: route_request(state, tool_selector))
    graph.add_node("inspect", lambda state: inspect_repository(state, _github_client()))
    graph.add_node(
        "answer_question", lambda state: answer_repository_question(state, model)
    )
    graph.add_node("list_repository_files", list_repository_files)
    graph.add_node(
        "read_repository_files",
        lambda state: read_repository_files(state, model, _github_client()),
    )
    graph.add_node("understand", lambda state: summarize_requirement(state, model))
    graph.add_node(
        "identify_requirements",
        lambda state: identify_deployment_requirements(state, structured_model),
    )
    graph.add_node(
        "generate", lambda state: generate_deployment_files(state, _github_client())
    )
    graph.add_node(
        "generate_dockerfile_only",
        lambda state: generate_dockerfile_only(state, _github_client()),
    )
    graph.add_node(
        "generate_ci_cd_pipeline",
        lambda state: generate_ci_cd_pipeline(
            state, helm_values_model, _github_client()
        ),
    )
    graph.add_node(
        "generate_helm_chart_only",
        lambda state: generate_helm_chart_only(
            state, helm_values_model, _github_client()
        ),
    )
    graph.add_node("validate", validate_deployment_files)
    graph.add_node(
        "analyze_errors", lambda state: analyze_validation_errors(state, model)
    )
    graph.add_node(
        "repair_errors",
        lambda state: repair_validation_errors(state, validation_repair_model),
    )
    graph.add_node(
        "prepare_preview",
        lambda state: prepare_pull_request_preview(state, _github_client()),
    )
    graph.set_entry_point("inspect")
    graph.add_edge("inspect", "select_tool")
    graph.add_conditional_edges(
        "select_tool",
        lambda state: state["tool_selection"].selected_tool,
        {
            "list_repository_files": "list_repository_files",
            "answer_repository_question": "answer_question",
            "read_repository_files": "read_repository_files",
            "create_dockerfile_only": "generate_dockerfile_only",
            "create_ci_cd_pipeline": "generate_ci_cd_pipeline",
            "create_helm_chart_only": "generate_helm_chart_only",
            "generate_deployment_configuration": "understand",
        },
    )
    graph.add_edge("answer_question", END)
    graph.add_edge("list_repository_files", END)
    graph.add_edge("read_repository_files", END)
    graph.add_edge("generate_dockerfile_only", "prepare_preview")
    graph.add_edge("generate_ci_cd_pipeline", "prepare_preview")
    graph.add_edge("understand", "identify_requirements")
    graph.add_edge("generate_helm_chart_only", "prepare_preview")
    graph.add_edge("identify_requirements", "generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges(
        "validate",
        lambda state: (
            "prepare_preview"
            if not state["validation_errors"]
            else (
                "repair_errors"
                if should_attempt_validation_repair(state)
                else "analyze_errors"
            )
        ),
        {
            "prepare_preview": "prepare_preview",
            "repair_errors": "repair_errors",
            "analyze_errors": "analyze_errors",
        },
    )
    graph.add_edge("repair_errors", "validate")
    graph.add_edge("analyze_errors", END)
    graph.add_edge("prepare_preview", END)
    return graph.compile()


def run_agent(repository: str, requirement: str) -> AgentState:
    match = re.fullmatch(r"([^/\s]+)/([^/\s]+)", repository.strip())
    if not match:
        raise ValueError("Repository must be specified as OWNER/REPOSITORY")
    owner, repo = match.groups()

    app = build_graph()
    return app.invoke(
        {
            "repository": repository,
            "requirement": requirement,
            "owner": owner,
            "repo": repo,
        }
    )


def publish_agent_result(result: AgentState) -> AgentState:
    return publish_preview(result, _github_client())
