from langchain_core.language_models.chat_models import BaseChatModel

from deployment_agent.agent.models import AgentState
from deployment_agent.tools.yaml_validator import validate_files


def validate_deployment_files(state: AgentState) -> AgentState:
    return {
        "validation_errors": validate_files(
            state["generated_files"], state["plan"], state.get("source_files", {})
        )
    }


def analyze_validation_errors(
    state: AgentState, model: BaseChatModel
) -> AgentState:
    response = model.invoke(
        "Analyze these deployment-file validation failures. Explain likely causes "
        "and actionable fixes concisely. Do not claim to have fixed them.\n\n"
        + "\n".join(state["validation_errors"])
    )
    return {"validation_analysis": str(response.content)}
