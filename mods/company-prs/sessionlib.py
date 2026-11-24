"""Stash, Jira and herdr helpers for the Pixel HQ PR panel, with no dependency outside this folder.

The Jira and Stash addresses and the Jira project keys come from ~/.config/pixel-hq/tickets.json
(see tickets.example.json). Without that file the panel shows no ticket and no PR."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

HOME = Path.home()
CACHE_DIR = HOME / ".cache/pixel-hq-prs"
JIRAFLOW_DB = HOME / ".config/jiraflow/state.db"
CONFIG_FILE = HOME / ".config/pixel-hq/tickets.json"


def load_config():
    try:
        config = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


CONFIG = load_config()
JIRA_URL = str(CONFIG.get("jira_url") or "").rstrip("/")
PROJECTS = [str(p) for p in CONFIG.get("ticket_projects") or [] if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", str(p))]
KEY = rf"(?:{'|'.join(PROJECTS)})-\d+"
PUBLIC_CONFIG = {"jira_url": JIRA_URL, "ticket_projects": PROJECTS}
JIRA_CACHE = CACHE_DIR / "jira.json"
JIRA_TTL = 600
STASH_URL = str(CONFIG.get("stash_url") or "").rstrip("/")
STASH_API = f"{STASH_URL}/rest/api/1.0"
TICKET_RE = re.compile(rf"\b({KEY})\b" if PROJECTS else r"(?!)()", re.I)
PR_RE = re.compile(r"/projects/([^/]+)/repos/([^/]+)/pull-requests/(\d+)")
BRANCH_RE = re.compile(
    rf"\b(?:feat|feature|fix|bugfix|hotfix|chore|docs|refactor|no-bump)/({KEY})[\w.-]*" if PROJECTS else r"(?!)()", re.I)
BRANCH_CMD_RE = re.compile(r"\bgit\b.*\b(?:push|switch\s+(?:-q\s+)?-c|checkout\s+-b|branch\s+-m|worktree\s+add)\b", re.S)
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
    if not token or not STASH_URL:
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
    if not token or not STASH_URL:
        return None
    try:
        res = subprocess.run(
            ["curl", "-sf", "-m", "15", "-H", f"Authorization: Bearer {token}", url],
            capture_output=True, text=True, timeout=20,
        )
        return json.loads(res.stdout) if res.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def reviewers(pr, status):
    return sorted(r["user"]["name"] for r in pr.get("reviewers", []) if r["status"] == status)


def human_comments(base):
    """Comment activities of the PR written by someone else than me or a bot, the last one first."""
    me = stash_user()
    activities = (stash_get(f"{base}/activities?limit=100") or {}).get("values", [])
    return [a for a in activities
            if a["action"] == "COMMENTED" and a["user"]["name"] != me and not BOT_RE.search(a["user"]["name"])]


def review_label(pr, human):
    approved = reviewers(pr, "APPROVED")
    needs_work = reviewers(pr, "NEEDS_WORK")
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


def ticket_info(key):
    """Summary and status of a ticket: from the jira-flow cache, else from Jira, kept ten minutes."""
    info = jira_tickets().get(key)
    if info:
        return info
    try:
        cache = json.loads(JIRA_CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(key)
    if hit and time.time() - hit.get("at", 0) < JIRA_TTL:
        return hit
    token = os.environ.get("JIRA_TOKEN")
    if not token or not JIRA_URL:
        return hit or {}
    try:
        res = subprocess.run(
            ["curl", "-sf", "-m", "10", "-H", f"Authorization: Bearer {token}",
             f"{JIRA_URL}/rest/api/2/issue/{key}?fields=summary,status"],
            capture_output=True, text=True, timeout=15,
        )
        fields = json.loads(res.stdout)["fields"] if res.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        fields = None
    if not fields:
        return hit or {}
    status = fields.get("status") or {}
    info = {"summary": fields.get("summary"), "status": status.get("name"),
            "category": (status.get("statusCategory") or {}).get("name"), "at": time.time()}
    cache[key] = info
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JIRA_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(JIRA_CACHE)
    return info
