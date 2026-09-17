"""Respond to newly opened GitHub issues and pull requests."""

import os
import sys

from github import Github


def main():
    """Post a greeting and apply the appropriate triage label."""
    # Fetch environment variables provided by GitHub Actions
    token = os.getenv("GITHUB_TOKEN")
    event_name = os.getenv("EVENT_NAME")
    item_number = os.getenv("ISSUE_NUMBER")
    repo_name = os.getenv("REPOS")

    if not all([token, event_name, item_number, repo_name]):
        print("Missing required environment variables.")
        sys.exit(1)

    # Authenticate with GitHub
    g = Github(token)
    repo = g.get_repo(repo_name)
    item_id = int(item_number)

    # Handle New Issues
    if event_name == "issues":
        issue = repo.get_issue(number=item_id)
        print(f"Processing newly opened Issue #{item_id}...")

        # Add an automated response
        issue.create_comment(
            f"Thank you for opening this issue, @{issue.user.login}! "
            "We will review it shortly. Please ensure you have included "
            "step-by-step reproduction steps."
        )
        # Apply a label
        issue.add_to_labels("triage")

    # Handle New Pull Requests
    elif event_name == "pull_request_target":
        pr = repo.get_pull(number=item_id)
        print(f"Processing newly opened PR #{item_id}...")

        # Add an automated response
        pr.create_issue_comment(
            f"Thanks for the contribution, @{pr.user.login}! "
            "Our automated checks are running. A maintainer will look at your "
            "code soon."
        )
        # Apply a label
        pr.add_to_labels("needs review")


if __name__ == "__main__":
    main()
