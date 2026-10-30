"""
Zero-Dependency GitHub Publisher (`push_to_github.py`)

Pushes the entire `daily-activity-agent` project to GitHub using EITHER:
1. Local `git` executable (if installed in PATH or standard Windows locations), OR
2. Direct GitHub REST API v3 (`https://api.github.com`) over HTTPS (works even when `git` is NOT installed!).
"""

import base64
import getpass
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()

TRACKED_FILES = [
    ".gitignore",
    ".env.example",
    "README.md",
    "requirements.txt",
    "database.py",
    "integrations.py",
    "agent_service.py",
    "antigravity_agent.py",
    "app.py",
    "push_to_github.py",
    "static/index.html",
    "static/styles.css",
    "static/app.js",
]


def find_git_executable() -> str | None:
    """Locate git.exe on PATH or standard Windows installation directories."""
    git_in_path = shutil.which("git")
    if git_in_path:
        return git_in_path

    common_paths = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\GitHubDesktop\app-*\resources\app\git\cmd\git.exe"),
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p
    return None


def github_api_request(
    method: str,
    url: str,
    token: str,
    payload: dict | None = None,
) -> tuple[int, dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "PulseOps-Daily-Activity-Agent",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(err_body)
        except Exception:
            return exc.code, {"message": err_body}


def push_via_github_rest_api(
    token: str,
    repo_name: str,
    private: bool = False,
    commit_message: str = "Initial commit: PulseOps Daily Activity & Security Operations AI Agent",
) -> str:
    """
    Creates the repository (if it doesn't exist) and uploads all project files
    directly via the GitHub Contents API — no local `git` installation required.
    """
    status, user_info = github_api_request("GET", "https://api.github.com/user", token)
    if status != 200:
        raise RuntimeError(f"GitHub authentication failed (HTTP {status}): {user_info.get('message')}")

    owner = user_info["login"]
    print(f"[+] Authenticated as GitHub user: {owner}")

    # Check if repo exists; if not, create it
    status, repo_info = github_api_request(
        "GET", f"https://api.github.com/repos/{owner}/{repo_name}", token
    )
    if status == 404:
        print(f"[+] Creating new {'private' if private else 'public'} repository '{owner}/{repo_name}'...")
        c_status, repo_info = github_api_request(
            "POST",
            "https://api.github.com/user/repos",
            token,
            {
                "name": repo_name,
                "description": "PulseOps — Daily Activity, Google Calendar Sync, Timesheet Webhook & Password Hygiene AI Agent",
                "private": private,
                "auto_init": True,
            },
        )
        if c_status not in (200, 201):
            raise RuntimeError(f"Failed creating repository (HTTP {c_status}): {repo_info.get('message')}")
    else:
        print(f"[+] Using existing repository: {owner}/{repo_name}")

    # Upload each file via PUT /repos/{owner}/{repo}/contents/{path}
    for rel_path in TRACKED_FILES:
        file_path = PROJECT_DIR / rel_path
        if not file_path.exists():
            continue
        raw_bytes = file_path.read_bytes()
        encoded = base64.b64encode(raw_bytes).decode("ascii")

        content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{rel_path}"
        get_status, existing = github_api_request("GET", content_url, token)

        put_payload = {
            "message": commit_message,
            "content": encoded,
            "author": {
                "name": "Git-LimbadriRacharla",
                "email": "limbadri3214@gmail.com",
            },
            "committer": {
                "name": "Git-LimbadriRacharla",
                "email": "limbadri3214@gmail.com",
            },
        }
        if get_status == 200 and isinstance(existing, dict) and existing.get("sha"):
            put_payload["sha"] = existing["sha"]

        put_status, put_resp = github_api_request("PUT", content_url, token, put_payload)
        if put_status in (200, 201):
            print(f"    [OK] Pushed {rel_path}")
        else:
            print(f"    [!] Failed pushing {rel_path} (HTTP {put_status}): {put_resp.get('message')}")

    repo_url = f"https://github.com/{owner}/{repo_name}"
    print(f"\n[SUCCESS] Code pushed to: {repo_url}")
    return repo_url


def push_via_git_cli(git_exe: str, remote_url: str) -> None:
    """Initialize git repo, commit all files, and push to remote_url."""
    def run_git(*args: str) -> None:
        subprocess.run([git_exe, *args], cwd=str(PROJECT_DIR), check=True)

    run_git("init", "-b", "main")
    run_git("add", ".")
    subprocess.run(
        [git_exe, "commit", "-m", "Initial commit: PulseOps Daily Activity AI Agent"],
        cwd=str(PROJECT_DIR),
        check=False,
    )
    subprocess.run([git_exe, "remote", "remove", "origin"], cwd=str(PROJECT_DIR), check=False)
    run_git("remote", "add", "origin", remote_url)
    run_git("push", "-u", "origin", "main")
    print(f"\n[SUCCESS] Pushed to {remote_url}")


def load_local_dotenv() -> None:
    """Load key=value pairs from .env if present."""
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    load_local_dotenv()
    print("=== PulseOps GitHub Publisher ===")
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo_name = os.getenv("GITHUB_REPO", "daily-activity-agent").strip()
    private_flag = os.getenv("GITHUB_PRIVATE", "false").lower() in ("1", "true", "yes")

    if not token:
        print(
            "\nNote: Direct GitHub API publishing works even without Git installed!\n"
            "Create a Personal Access Token (with 'repo' / 'Contents: Read & Write' permission) at:\n"
            "  https://github.com/settings/tokens\n"
        )
        token = getpass.getpass("Enter your GitHub Personal Access Token (or press Enter to try git CLI): ").strip()

    if token:
        custom_repo = input(f"Repository name [{repo_name}]: ").strip()
        if custom_repo:
            repo_name = custom_repo
        vis = input("Make repository private? (y/N): ").strip().lower()
        private_flag = vis.startswith("y")
        push_via_github_rest_api(token=token, repo_name=repo_name, private=private_flag)
        return

    git_exe = find_git_executable()
    if not git_exe:
        print(
            "\n[!] `git` was not found on your Windows PATH, and no GITHUB_TOKEN was provided.\n"
            "    Either re-run `python push_to_github.py` and paste a GitHub Personal Access Token,\n"
            "    or install Git for Windows (`winget install --id Git.Git -e --source winget`)."
        )
        sys.exit(1)

    remote_url = input("Enter your GitHub repository URL (e.g. https://github.com/username/daily-activity-agent.git): ").strip()
    if not remote_url:
        print("[!] Remote URL is required for git CLI push.")
        sys.exit(1)
    push_via_git_cli(git_exe, remote_url)


if __name__ == "__main__":
    main()
