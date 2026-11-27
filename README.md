# Deployment Agent

A Python CLI that uses Azure OpenAI and LangGraph to inspect a GitHub repository, generate GitHub Actions and Helm files, validate them, and open a pull request.

See the [Deployment Agent guide](AGENT_GUIDE.md) for the architecture,
capabilities, Helm and secret behavior, validation, setup, and troubleshooting.

## Requirements

- Python 3.10+
- An Azure OpenAI deployment
- A GitHub token with repository contents and pull-request write access
- `helm` and `yamllint` on `PATH` (required to validate full deployment generation)
- Docker Buildx with `docker build --check` support (used for non-executing Dockerfile validation when a Dockerfile is present)

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

## Chat UI

Start the chat interface from the project root:

```powershell
python -m streamlit run src/deployment_agent/ui.py
```

Enter the GitHub repository as `OWNER/REPOSITORY`, then ask a question or describe
the deployment changes you want in natural language; shorthand and minor typos
are okay. Repository questions are read-only. Explicit deployment-change
requests run validation and prepare a preview when all checks pass. The UI and
CLI show proposed diffs and require confirmation before creating or updating a
pull request. A request only to create a Dockerfile uses a dedicated path: it detects the
project from repository files, selects the matching template, skips workflow/Helm
generation and validation, and prepares a preview containing only the Dockerfile.
CI/CD requests use the matching CI and CD GitHub Actions templates under
`templates/GHA-Workflows/` and skip validation.
Helm-only requests generate the shared ConfigMap and `values.yaml` files
without a workflow or local validation; they do not create a full standalone
Helm chart, and do not require Helm or Docker to be installed.
Helm chart ConfigMap and values files are also created in
`sandeepshankar1094-creator/Helm-Charts` under
`Application/<repo-prefix>/<repo-name>/`, using the templates in
`templates/Helm-Charts/`. The prefix is the part of the application repository
name before its first hyphen (for example, `java-springboot` maps to
`Application/java/java-springboot/`). CD and CI/CD requests prepare changes for
the application repository's workflows and a separate PR preview for chart
configuration in the shared Helm-Charts repository.
When a Helm request names secrets (for example, `Add this api-key into
poc-ai-agent service`), the same name is added to `app.containers.env` as
`name@azurekeyvault` and to `app.kvSecrets`. The secret value itself is never
written into Helm values; add it separately to the configured Azure Key Vault.
Existing Key Vault secret references and Helm settings are read from both the
shared repository's `agent-automation` branch and its default branch. The
default-branch values are merged first, then `agent-automation` values take
precedence for ordinary settings; Key Vault references are unioned. Conflicting
ordinary values are reported in the preview without printing their contents.
To intentionally remove a secret, say, for example, `Remove the secret named
api-key from Helm values`. The removal is recorded in a YAML comment so later
updates do not restore it from the default branch. Explicitly requesting the
same secret again clears that removal. Do not paste actual secret values into
prompts.
To set other `values.yaml` parameters, include a fenced YAML mapping in the
prompt using the same top-level keys and nesting as the template. Any existing
parameter can be overridden; unspecified parameters retain existing shared-repo
values when available, otherwise they keep their template defaults.
For example:

```yaml
app:
  replicaCount: 3
  autoscaleEnabled: false
  containers:
    port: 9090
    envCode: qa
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
ingress:
  enabled: false
service:
  port: 9090
  targetPort: 9090
```

Overrides for unknown parameter names are rejected rather than silently ignored.
Common natural-language changes are also supported, for example
“Increase replicas to 3” or “Set the container port to 9090”. The agent uses
Azure OpenAI to map these requests to existing template keys; explicit YAML
overrides take precedence when both formats are supplied.
You can also provide exact service endpoints, for example “Set the HTTPS
destination to `api.example.com` and Redis URL to `cache.example.net`”, or use
a fenced YAML mapping. The agent copies supplied hostnames, URLs, and IP
addresses exactly; it does not infer them. The template's `poc.ai-agent.com`
and `demo.redis.cache.windows.net` values remain examples and should be replaced
with the intended environment values before publishing.

Azure OpenAI selects from the available repository and deployment tools based on
each prompt. It can list repository files, answer from the file inventory, read
up to three selected files to answer a question, or run the deployment workflow.
Validated deployment changes are previewed before publishing. For a
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

- `agent/` contains LangGraph orchestration, request routing, and shared
  state/request models.
- `tools/` contains repository, deployment, validation, and GitHub PR activities,
  Helm values rendering, preview/publication flows, and the deployment and YAML
  validator implementations.
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
For Helm repository updates, the token must also have **Contents: Read and
write** and **Pull requests: Read and write** access to
`sandeepshankar1094-creator/Helm-Charts`, as well as the source repository.

## Run

```powershell
deployment-agent --repo OWNER/REPOSITORY --requirement "Build and deploy this service to Kubernetes"
```

The agent uses the shared `agent-automation` branch for generated changes and
updates that branch and its open PR on subsequent confirmed requests. A
validation repair loop may make up to two Azure-assisted attempts for generated
YAML/Helm errors; repairs are restricted to generated YAML and preserve existing
Key Vault references. If validation still fails, no preview is publishable.
Dockerfile-only requests, CI/CD template requests, and Helm-chart-only requests
skip validation; all generated changes require preview confirmation before
creating or updating the PR.
The agent does not merge the PR. The CI/CD templates currently support Maven and
Angular projects and target AKS; configure the Azure credentials, resource group,
and cluster details in the selected CD workflow before running it. Existing
generated paths are updated on the shared branch. An explicitly requested
Dockerfile is regenerated from its selected template, including when a Dockerfile
already exists.

Validation does not execute the repository's Docker build. When a Dockerfile is
present, the agent invokes `docker build --check` to perform BuildKit checks
without running build steps; only the Dockerfile is fetched, so source-dependent
build behavior is not verified. Unchanged generated content is not committed
again. Transient GitHub reads and idempotent updates use bounded retries.
Validation failures that cannot be repaired are sent to Azure OpenAI for
analysis, and no branch or PR is created.

## Flow

CI/CD template requests detect the repository stack, copy the corresponding
workflow templates and prepare a preview without running validation. Other
deployment requests follow the plan, generation, validation, preview, and
confirmation flow.

The CLI displays a diff and asks for confirmation interactively. To publish
without an interactive prompt, pass `--yes`; this publishes immediately after
displaying the diff:

```powershell
deployment-agent --repo OWNER/REPOSITORY --requirement "Increase replicas to 3" --yes
```
