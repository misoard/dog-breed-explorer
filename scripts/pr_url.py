"""
Print a GitHub compare URL with the PR title and body pre-filled.

Used by /ship. The point is to keep the human checkpoint while removing the
copy-paste: the link opens GitHub's "Open a pull request" form already filled in,
and the user still reviews it and clicks Create. An agent that opened and merged
its own PRs would have reinvented pushing to main with extra ceremony.

Usage:
    python scripts/pr_url.py --branch m5-ci --title "M5 — CI on PR + daily cron" \
                            --body-file /tmp/pr_body.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

# GitHub accepts long query strings, but browsers and proxies get unhappy past ~8k.
# A PR body worth reading is ~1-2k; if we're near the ceiling the body is too long
# for a PR body anyway -- that's what DECISIONS.md is for.
MAX_URL = 8000


def remote_slug() -> str:
    """owner/repo, from whichever remote form is configured."""
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    # git@github.com:owner/repo.git  |  https://github.com/owner/repo.git
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"cannot parse an owner/repo out of: {url}")
    return m.group(1)


def base_branch() -> str:
    """The default branch — what the PR targets. Don't assume it's called main."""
    try:
        ref = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return ref.rsplit("/", 1)[-1]
    except subprocess.CalledProcessError:
        return "main"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--branch", required=True, help="the head branch (the work)")
    ap.add_argument("--title", required=True, help="one sentence: what changed")
    ap.add_argument("--body-file", type=Path, help="markdown file with the PR body")
    ap.add_argument("--base", default=None, help="target branch (default: the repo's default)")
    args = ap.parse_args()

    base = args.base or base_branch()
    body = args.body_file.read_text() if args.body_file else ""

    url = (
        f"https://github.com/{remote_slug()}/compare/{base}...{quote(args.branch)}"
        f"?expand=1&title={quote(args.title)}&body={quote(body)}"
    )

    if len(url) > MAX_URL:
        print(
            f"  ! body is long ({len(url)} chars of URL). Browsers may truncate it.\n"
            f"  ! A PR body that long belongs in DECISIONS.md — the PR should POINT at it.\n",
            file=sys.stderr,
        )

    print(f"\n  Open the PR (title + body pre-filled — review, then click Create):\n\n    {url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
