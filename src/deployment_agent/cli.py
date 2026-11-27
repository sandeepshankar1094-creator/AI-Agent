import argparse
import sys

from deployment_agent.agent.graph import publish_agent_result, run_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and PR deployment files.")
    parser.add_argument("--repo", required=True, help="GitHub repository as OWNER/REPOSITORY")
    parser.add_argument("--requirement", required=True, help="Build and deployment requirement")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Publish the generated preview without an interactive confirmation.",
    )
    args = parser.parse_args()

    try:
        result = run_agent(args.repo, args.requirement)
    except Exception as exc:
        print(f"Agent failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if result.get("validation_errors"):
        print("Validation failed; no PR was created.")
        print(result.get("validation_analysis", ""))
        raise SystemExit(2)

    if result.get("response"):
        print(result["response"])
        return
    for warning in result.get("helm_merge_warnings", []):
        print(f"Warning: {warning}")
    changes = result.get("preview_changes", [])
    if not changes:
        print("No changes to publish.")
        return
    print(f"Preview: {len(changes)} file(s) will be changed.")
    for change in changes:
        print(f"\n{change['repository']} - {change['path']}")
        print(change["diff"], end="" if change["diff"].endswith("\n") else "\n")

    approved = args.yes
    if not approved and sys.stdin.isatty():
        approved = input("\nCreate or update the pull request(s)? [y/N] ").strip().lower() in {
            "y",
            "yes",
        }
    if not approved:
        print("No PR was created. Re-run with --yes to publish non-interactively.")
        return

    try:
        result = publish_agent_result(result)
    except Exception as exc:
        print(f"Publishing failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    urls = result.get("pull_request_urls") or [result["pull_request_url"]]
    for url in urls:
        print(f"Pull request created: {url}")


if __name__ == "__main__":
    main()
