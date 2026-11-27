from deployment_agent.agent.models import AgentState
from deployment_agent.integrations.github_api import GitHubClient


def inspect_repository(state: AgentState, client: GitHubClient) -> AgentState:
    branch, tree = client.inspect_repository(state["owner"], state["repo"])
    return {"default_branch": branch, "tree": tree}
