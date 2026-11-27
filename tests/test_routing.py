from deployment_agent.agent.models import ToolSelection
from deployment_agent.agent.routing import route_request


def test_helm_parameter_phrase_overrides_repository_question_selection():
    class FakeSelector:
        def invoke(self, prompt):
            assert "Update the auto scale min value also to 5" in prompt
            return ToolSelection(
                selected_tool="read_repository_files",
                normalized_request="Look for auto scale settings.",
                file_paths=["application.properties"],
            )

    result = route_request(
        {
            "repository": "acme/service",
            "requirement": "Update the auto scale min value also to 5",
            "tree": [{"path": "application.properties", "type": "blob"}],
        },
        FakeSelector(),
    )

    assert result["tool_selection"].selected_tool == "create_helm_chart_only"
