import streamlit as st

from deployment_agent.agent.graph import run_agent
from deployment_agent.agent.models import AgentState


def _format_result(result: AgentState) -> str:
    if result.get("response"):
        return result["response"]
    if result.get("validation_errors"):
        analysis = result.get("validation_analysis", "No analysis was returned.")
        errors = "\n".join(f"- {error}" for error in result["validation_errors"])
        return f"**Validation failed; no PR was created.**\n\n{errors}\n\n{analysis}"
    return f"Pull request created: [{result['pull_request_url']}]({result['pull_request_url']})"


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
        "Repository questions are read-only. Dockerfile-only requests create a "
        "pull request without validation. CI/CD requests use the matching "
        "repository workflow templates and also skip validation; other deployment "
        "changes are validated before a pull request is created."
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask a question or describe a deployment change...")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if not repository.strip():
            response = "Enter a GitHub repository as `OWNER/REPOSITORY` before submitting a prompt."
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
                    if result.get("validation_errors"):
                        st.error(response)
                    else:
                        st.success(response)

    st.session_state.messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
