import argparse
import sys

from deployment_agent.agent.graph import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and PR deployment files.")
    parser.add_argument("--repo", required=True, help="GitHub repository as OWNER/REPOSITORY")
    parser.add_argument("--requirement", required=True, help="Build and deployment requirement")
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
    print(f"Pull request created: {result['pull_request_url']}")


if __name__ == "__main__":
    main()
