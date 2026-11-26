from langchain_core.messages import AIMessage
import pytest

from deployment_agent.agent import graph
from deployment_agent.agent.models import ToolSelection
from deployment_agent.tools.repository import format_repository_file_list


def test_formats_exact_repository_file_paths():
    tree = [
        {"path": "src/main.py", "type": "blob"},
        {"path": "src", "type": "tree"},
        {"path": "README.md", "type": "blob"},
    ]

    assert format_repository_file_list(tree) == (
        "Files in the repository:\n- README.md\n- src/main.py"
    )


def test_file_listing_uses_read_only_github_inspection(monkeypatch):
    class FakeGitHubClient:
        def inspect_repository(self, owner, repo):
            assert (owner, repo) == ("acme", "service")
            return "main", [{"path": "README.md", "type": "blob"}]

    class FakeSelector:
        def invoke(self, prompt):
            assert "List the files in the repo" in prompt
            return ToolSelection(
                selected_tool="list_repository_files",
                normalized_request="List the repository files.",
            )

    class FakeModel:
        def with_structured_output(self, schema):
            if schema is ToolSelection:
                return FakeSelector()
            return self

        def invoke(self, prompt):
            return AIMessage(content="Unexpected model call")

    monkeypatch.setattr(graph, "_github_client", FakeGitHubClient)
    monkeypatch.setattr(graph, "_chat_model", FakeModel)

    result = graph.run_agent("acme/service", "List the files in the repo")

    assert result["response"] == "Files in the repository:\n- README.md"
    assert "generated_files" not in result


def test_model_selected_file_reader_fetches_only_repository_paths(monkeypatch):
    class FakeGitHubClient:
        def inspect_repository(self, owner, repo):
            return "main", [{"path": "README.md", "type": "blob"}]

        def get_file(self, owner, repo, path, ref):
            assert (owner, repo, path, ref) == (
                "acme",
                "service",
                "README.md",
                "main",
            )
            return "# Example service"

    class FakeSelector:
        def invoke(self, prompt):
            return ToolSelection(
                selected_tool="read_repository_files",
                normalized_request="Summarize README.md.",
                file_paths=["README.md"],
            )

    class FakeModel:
        def with_structured_output(self, schema):
            if schema is ToolSelection:
                return FakeSelector()
            return self

        def invoke(self, prompt):
            assert "# Example service" in prompt
            return AIMessage(content="It is an example service.")

    monkeypatch.setattr(graph, "_github_client", FakeGitHubClient)
    monkeypatch.setattr(graph, "_chat_model", FakeModel)

    result = graph.run_agent("acme/service", "What does the readme say?")

    assert result["response"] == "It is an example service."


def test_model_selected_file_reader_rejects_paths_outside_repository(monkeypatch):
    class FakeGitHubClient:
        def inspect_repository(self, owner, repo):
            return "main", [{"path": "README.md", "type": "blob"}]

    class FakeSelector:
        def invoke(self, prompt):
            return ToolSelection(
                selected_tool="read_repository_files",
                normalized_request="Read a file.",
                file_paths=["../secrets.txt"],
            )

    class FakeModel:
        def with_structured_output(self, schema):
            if schema is ToolSelection:
                return FakeSelector()
            return self

    monkeypatch.setattr(graph, "_github_client", FakeGitHubClient)
    monkeypatch.setattr(graph, "_chat_model", FakeModel)

    with pytest.raises(RuntimeError, match="not present in the repository tree"):
        graph.run_agent("acme/service", "Read the secret file")
