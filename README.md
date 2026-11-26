# Deployment Agent

A Python CLI that uses Azure OpenAI and LangGraph to inspect a GitHub repository, generate GitHub Actions and Helm files, validate them, and open a pull request.

## Requirements

- Python 3.10+
- An Azure OpenAI deployment
- A GitHub token with repository contents and pull-request write access
- `helm` on `PATH` (required to validate the generated chart)
- `yamllint` on `PATH` (required to lint generated YAML)
- Docker Buildx with `docker build --check` support (used for non-executing Dockerfile validation when a Dockerfile is present)

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Chat UI

Start the chat interface from the project root:

```powershell
python -m streamlit run src/deployment_agent/ui.py
```

Enter the GitHub repository as `OWNER/REPOSITORY`, then ask a question or describe
the deployment changes you want in natural language; shorthand and minor typos
are okay. Repository questions are read-only. Explicit deployment-change
requests run validation and may create a branch and pull request when all checks
pass. A request only to create a Dockerfile uses a dedicated path: it detects the
project from repository files, selects the matching template, skips workflow/Helm
generation and validation, and creates a PR containing only the Dockerfile.
CI/CD requests use the matching CI and CD GitHub Actions templates under
`templates/GHA-Workflows/` and skip validation.

Azure OpenAI selects from the available repository and deployment tools based on
each prompt. It can list repository files, answer from the file inventory, read
up to three selected files to answer a question, or run the deployment workflow.
Validated deployment changes continue to create a PR automatically. For a
Dockerfile-only request, the agent detects Maven projects from `pom.xml` and
Node projects from `package.json`, then uses the matching template in
`templates/Dockerfiles/` (`Maven`, `Node` for Angular, or `NodeServer` for a
Node server). Angular projects are detected from `angular.json` and the Node
template's output path is filled from the project's build configuration. The
Maven and Angular Dockerfiles expect CI to
produce `target/*.jar` or the configured Angular `dist/` output before the
Docker image is built; neither compiles the project inside the Docker build.
The generated deployment workflow currently builds and pushes the image, so
ensure those application build steps run earlier in your CI workflow. The Node
template runs server applications with `npm start`. Explicit Dockerfile requests
regenerate the file from its template; for monorepos, include the target project
directory in the prompt.

The source is organized by responsibility:

- `agent/` contains LangGraph orchestration and shared state/request models.
- `tools/` contains repository, deployment, validation, and GitHub PR activities,
  plus the deployment generator and YAML validator implementations.
- `integrations/` contains external service clients such as the GitHub REST API.
- `cli.py` and `ui.py` are the command-line and Streamlit entry points.

Create a `.env` file in the project root and fill in your credentials:

```dotenv
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
GITHUB_TOKEN=<fine-grained-token>
```

The application loads `.env` automatically. `.env` is ignored by Git; do not commit credentials. For GitHub Enterprise Server, you can optionally add `GITHUB_API_URL=https://github.example.com/api/v3`. The default is `https://api.github.com`.

## Run

```powershell
deployment-agent --repo OWNER/REPOSITORY --requirement "Build and deploy this service to Kubernetes"
```

The agent uses the shared `agent-automation` branch for generated changes and
updates that branch and its open PR on subsequent requests. Dockerfile-only
requests and CI/CD template requests skip validation; other deployment requests
create or update the PR only after validation succeeds. The agent does not merge
the PR. The CI/CD templates currently support Maven and Angular projects and
target AKS; configure the Azure credentials, resource group, and cluster details
in the selected CD workflow before running it. Existing generated paths are
updated on the shared branch. An explicitly requested Dockerfile is regenerated
from its selected template, including when a Dockerfile already exists.

Validation does not execute the repository's Docker build. When a Dockerfile is present, the agent invokes `docker build --check` to perform BuildKit checks without running build steps; only the Dockerfile is fetched, so source-dependent build behavior is not verified. Validation failures are sent to Azure OpenAI for analysis, and no branch or PR is created.

## Flow

CI/CD template requests detect the repository stack, copy the corresponding
workflow templates, and open or update the shared PR without running validation.
Other deployment requests follow the plan, generation, validation, and PR flow.
