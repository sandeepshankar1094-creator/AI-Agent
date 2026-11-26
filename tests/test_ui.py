from deployment_agent.ui import _format_result


def test_format_result_reports_validation_failure_without_pr():
    result = {
        "validation_errors": ["helm template failed"],
        "validation_analysis": "Check the chart templates.",
    }

    formatted = _format_result(result)

    assert "no PR was created" in formatted
    assert "helm template failed" in formatted
    assert "Check the chart templates." in formatted


def test_format_result_links_created_pull_request():
    result = {"pull_request_url": "https://github.example.com/pull/42"}

    assert _format_result(result) == (
        "Pull request created: "
        "[https://github.example.com/pull/42](https://github.example.com/pull/42)"
    )


def test_format_result_displays_repository_answer():
    result = {"response": "Files in the repository:\n- README.md"}

    assert _format_result(result) == "Files in the repository:\n- README.md"
