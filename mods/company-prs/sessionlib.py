"""Stash, Jira-cache and herdr helpers for the Pixel HQ PR panel, with no dependency outside this folder."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

HOME = Path.home()
CACHE_DIR = HOME / ".cache/pixel-hq-prs"
JIRAFLOW_DB = HOME / ".config/jiraflow/state.db"
STASH_URL = "https://bitbucket.example.com"
STASH_API = f"{STASH_URL}/rest/api/1.0"
TICKET_RE = re.compile(r"\b(PROJ-\d+)\b", re.I)
PR_RE = re.compile(r"/projects/([^/]+)/repos/([^/]+)/pull-requests/(\d+)")
BOT_RE = re.compile(r"robot|service-user|bot$|^svc", re.I)
TOKEN_FILES = (".zshrc", ".zprofile", ".zshenv", ".bash_tokens", ".bashrc")


def load_token(name):
    """Reads `export NAME=...` from the shell files: herdr started from the Dock has no shell environment."""
    if os.environ.get(name):
        return
    pattern = re.compile(rf"^\s*export\s+{name}=['\"]?([^'\"\s]+)", re.M)
    for f in TOKEN_FILES:
        try:
            match = pattern.search((HOME / f).read_text(errors="replace"))
        except OSError:
            continue
        if match:
            os.environ[name] = match.group(1)
            return


def hc_bin():
    return shutil.which("hc") or str(HOME / ".local/bin/hc")


def hc(*args):
    return subprocess.run([hc_bin(), *args], capture_output=True, text=True, timeout=10, check=True).stdout


def stash_user():
    """The Stash username that owns STASH_TOKEN, cached once found."""
    cache = CACHE_DIR / "stash-user"
    try:
        return cache.read_text().strip()
    except OSError:
        pass
    token = os.environ.get("STASH_TOKEN")
    if not token:
        return None
    res = subprocess.run(
        ["curl", "-s", "-m", "15", "-D", "-", "-o", "/dev/null",
         "-H", f"Authorization: Bearer {token}", f"{STASH_API}/users?limit=1"],
        capture_output=True, text=True, timeout=20,
    )
    match = re.search(r"^x-ausername:\s*(\S+)", res.stdout, re.I | re.M)
    if not match:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(match.group(1))
    return match.group(1)


def stash_get(url):
    token = os.environ.get("STASH_TOKEN")
    if not token:
        return None
    try:
        res = subprocess.run(
            ["curl", "-sf", "-m", "15", "-H", f"Authorization: Bearer {token}", url],
            capture_output=True, text=True, timeout=20,
        )
        return json.loads(res.stdout) if res.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def review_label(pr, base):
    me = stash_user()
    activities = (stash_get(f"{base}/activities?limit=100") or {}).get("values", [])
    approved = sorted(r["user"]["name"] for r in pr.get("reviewers", []) if r["status"] == "APPROVED")
    needs_work = sorted(r["user"]["name"] for r in pr.get("reviewers", []) if r["status"] == "NEEDS_WORK")
    human = [a for a in activities
             if a["action"] == "COMMENTED" and a["user"]["name"] != me and not BOT_RE.search(a["user"]["name"])]
    state = pr["state"]
    if state == "MERGED":
        return "merged"
    if state == "DECLINED":
        return "declined"
    if needs_work:
        return f"needs work ({', '.join(needs_work)})"
    if approved:
        return f"approved by {', '.join(approved)}"
    if human:
        return f"commented by {human[0]['user']['name']}"
    if pr.get("draft"):
        return "draft"
    return f"waiting for review ({len(pr.get('reviewers', []))} reviewers)"


def jira_tickets():
    """Tickets cached by jira-flow, when it is installed."""
    if not JIRAFLOW_DB.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{JIRAFLOW_DB}?mode=ro", uri=True) as c:
            rows = c.execute("select key, summary, status, status_category from tickets").fetchall()
    except sqlite3.Error:
        return {}
    return {k: {"summary": s, "status": st, "category": cat} for k, s, st, cat in rows}
