import streamlit as st

from deployment_agent.agent.graph import publish_agent_result, run_agent
from deployment_agent.agent.models import AgentState


def _format_result(result: AgentState) -> str:
    if result.get("response"):
        return result["response"]
    if result.get("validation_errors"):
        analysis = result.get("validation_analysis", "No analysis was returned.")
        errors = "\n".join(f"- {error}" for error in result["validation_errors"])
        return f"**Validation failed; no PR was created.**\n\n{errors}\n\n{analysis}"
    if "preview_changes" in result:
        if result["preview_changes"]:
            return (
                f"Preview ready for {len(result['preview_changes'])} file(s). "
                "Review the changes below, then choose whether to publish."
            )
        return "Generated files already match the target branches; no PR is needed."
    urls = result.get("pull_request_urls") or [result["pull_request_url"]]
    heading = "Pull request created:" if len(urls) == 1 else "Pull requests created:"
    return heading + "\n" + "\n".join(
        f"- [{url}]({url})" for url in urls
    )


def _show_preview(result: AgentState) -> None:
    for warning in result.get("helm_merge_warnings", []):
        st.warning(warning)
    for change in result.get("preview_changes", []):
        st.markdown(f"**{change['repository']} - `{change['path']}`**")
        st.code(change["diff"], language="diff")


def main() -> None:
    st.set_page_config(page_title="Deployment Agent")
    st.title("Deployment Agent")
    st.caption(
        "Ask naturally—shorthand and minor typos are okay. You can ask about the "
        "repository or request deployment changes."
    )

    repository = st.text_input(
        "GitHub repository",
        placeholder="OWNER/REPOSITORY",
        help="Use OWNER/REPOSITORY, for example contoso/web-service.",
    )
    st.warning(
        "Repository questions are read-only. Generated changes are previewed "
        "before publishing. Dockerfile-only requests skip validation. CI/CD "
        "requests use the matching "
        "repository workflow templates; CD requests also create ConfigMap and "
        "values files in the shared Helm-Charts repository. Helm-chart-only "
        "requests create those chart files there. These paths skip validation; "
        "other deployment changes are validated before a preview is offered."
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask a question or describe a deployment change...")
    if prompt:
        if st.session_state.pop("pending_result", None):
            notice = (
                "The previous preview was discarded because you submitted a new "
                "request; no PR was created for it."
            )
            st.session_state.messages.append({"role": "assistant", "content": notice})
            with st.chat_message("assistant"):
                st.info(notice)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if not repository.strip():
                response = (
                    "Enter a GitHub repository as `OWNER/REPOSITORY` before "
                    "submitting a prompt."
                )
                st.info(response)
            else:
                with st.spinner("Reviewing your request..."):
                    try:
                        result = run_agent(repository, prompt)
                    except Exception as exc:
                        response = f"Agent failed: {exc}"
                        st.error(response)
                    else:
                        response = _format_result(result)
                        if result.get("preview_changes"):
                            st.session_state.pending_result = result
                        if result.get("validation_errors"):
                            st.error(response)
                        else:
                            st.success(response)

        st.session_state.messages.append({"role": "assistant", "content": response})

    pending = st.session_state.get("pending_result")
    if pending:
        st.subheader("Review proposed changes")
        _show_preview(pending)
        approve_column, discard_column = st.columns(2)
        with approve_column:
            approve = st.button("Create or update pull request", type="primary")
        with discard_column:
            discard = st.button("Discard preview")
        if approve:
            with st.spinner("Publishing approved changes..."):
                try:
                    published = publish_agent_result(pending)
                except Exception as exc:
                    st.error(f"Could not publish the approved changes: {exc}")
                else:
                    response = _format_result(published)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": response}
                    )
                    st.success(response)
                    st.session_state.pop("pending_result", None)
        elif discard:
            notice = "Preview discarded; no PR was created."
            st.session_state.messages.append({"role": "assistant", "content": notice})
            st.info(notice)
            st.session_state.pop("pending_result", None)


if __name__ == "__main__":
    main()
