#!/usr/bin/env python3
"""Prints herdr terminals' Claude sessions, their PRs and docs as JSON for the Pixel HQ panels."""
import concurrent.futures
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sessionlib  # noqa: E402

sessionlib.load_token("STASH_TOKEN")
sessionlib.load_token("JIRA_TOKEN")

SESSIONS_DIR = Path.home() / ".claude/sessions"
PROJECTS_DIR = Path.home() / ".claude/projects"
PR_CACHE = sessionlib.CACHE_DIR / "prs.json"
PR_TTL = 120
PR_TTL_RUNNING = 20
RESUME_STATE = Path.home() / ".local/state/pixel-hq-resume.json"
PR_TTL_DECLINED = 3600
TICKET_STATE = sessionlib.CACHE_DIR / "session-prs.json"
NOTIFIED_STATE = sessionlib.CACHE_DIR / "notified.json"


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "terminals"
    if cmd == "prs":
        return print_prs(sys.argv[2], fresh="--fresh" in sys.argv[3:])
    if cmd == "changes":
        return print_changes()
    if cmd == "docs":
        return print_docs(sys.argv[2])
    if cmd == "failed":
        return print_failed()
    return print_terminals()


def print_terminals():
    """Every live terminal running Claude, with its session name and ticket. Also restarts sessions lost to a reboot."""
    live = live_by_pid()
    terminals, running, shells = {}, set(), {}
    for t in live_terminals():
        shells[t["address"]] = t
        s = live.get((t.get("foreground") or {}).get("pid"))
        if not s:
            continue
        running.add(s["sessionId"])
        name = s.get("name") or ""
        match = sessionlib.TICKET_RE.search(name)
        terminals[t["address"]] = {"id": s["sessionId"], "name": name, "cwd": s.get("cwd"),
                                   "ticket": match.group(1).upper() if match else None}
    talked = pr_tickets([v["id"] for v in terminals.values()])
    for v in terminals.values():
        mentioned = talked.get(v["id"], [])
        v["ticket"] = v["ticket"] or (mentioned[0] if mentioned else None)
        v["tickets"] = list(dict.fromkeys(([v["ticket"]] if v["ticket"] else []) + mentioned))
    resume_lost(terminals, shells, running)
    print(json.dumps({"terminals": terminals, "config": sessionlib.PUBLIC_CONFIG}))


def pr_tickets(session_ids):
    """The ticket keys in the titles of my PRs each session mentioned, the last mentioned first.
    Reads transcripts incrementally and PR titles from the cache only, so it stays cheap enough to poll."""
    try:
        state = json.loads(TICKET_STATE.read_text())
    except (OSError, ValueError):
        state = {}
    changed = False
    for sid in session_ids:
        seen = state.get(sid) or {}
        for path in transcripts(sid):
            size = path.stat().st_size
            same = seen.get("path") == str(path) and seen.get("offset", 0) <= size
            offset = seen.get("offset", 0) if same else 0
            if offset == size:
                break
            keys = list(seen.get("prs", [])) if same else []
            with path.open("rb") as fh:
                fh.seek(offset)
                for raw in fh:
                    if not raw.endswith(b"\n"):
                        break
                    offset += len(raw)
                    if b"pull-requests/" not in raw:
                        continue
                    line = raw.decode("utf-8", "replace")
                    # Claude Code repeats pr-link records for the branch's PR: only a written mention counts as recent.
                    relink = b'"type":"pr-link"' in raw
                    for m in sessionlib.PR_RE.finditer(authored_text(line)):
                        key = f"{m.group(1)}/{m.group(2)}#{m.group(3)}"
                        if key in keys:
                            if relink:
                                continue
                            keys.remove(key)
                        keys.append(key)
            state[sid] = {"path": str(path), "offset": offset, "prs": keys[-20:]}
            changed = True
            break
    if changed:
        TICKET_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TICKET_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(TICKET_STATE)
    cache = read_cache()
    me = sessionlib.stash_user()
    out = {}
    for sid in session_ids:
        found = []
        for key in reversed((state.get(sid) or {}).get("prs", [])):
            pr = cache.get(key) or {}
            if me and pr.get("author") != me:
                continue
            match = sessionlib.TICKET_RE.search(pr.get("title") or "")
            if match and match.group(1).upper() not in found:
                found.append(match.group(1).upper())
        out[sid] = found
    return out


def live_by_pid():
    out = {}
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            out[int(d["pid"])] = d
        except (OSError, ValueError, KeyError):
            continue
    return out


def live_terminals():
    listing = json.loads(sessionlib.hc("ls"))
    for t in listing.get("terminals", []):
        if t.get("state") == "live":
            try:
                yield json.loads(sessionlib.hc("get", t["address"]))
            except (subprocess.SubprocessError, ValueError):
                continue


def resume_lost(terminals, shells, running):
    """Types `claude --resume` into terminals herdr recreated as a bare shell (reboot, logout, crash)."""
    try:
        state = json.loads(RESUME_STATE.read_text())
    except (OSError, ValueError):
        state = {}
    for address, seen in state.items():
        t = shells.get(address)
        if not t or address in terminals or t.get("pid") == seen["shell"]:
            continue
        if seen["id"] in running:
            continue
        if (t.get("foreground") or {}).get("pid") not in (None, t.get("pid")):
            continue
        cwd = shlex.quote(seen["cwd"]) if seen.get("cwd") else "."
        subprocess.run([sessionlib.hc_bin(), "send", address, f"cd {cwd} && claude --resume {seen['id']}"],
                       capture_output=True, timeout=10)
        running.add(seen["id"])
    current = {a: {"id": v["id"], "cwd": v.get("cwd"), "shell": shells[a].get("pid")} for a, v in terminals.items()}
    for address, seen in state.items():
        t = shells.get(address)
        if address not in current and t and t.get("pid") == seen["shell"]:
            continue
        if address not in current and t and seen["id"] in running:
            current[address] = seen | {"shell": t.get("pid")}
    RESUME_STATE.parent.mkdir(parents=True, exist_ok=True)
    RESUME_STATE.write_text(json.dumps(current))


def session_of(address):
    pid = (json.loads(sessionlib.hc("get", address)).get("foreground") or {}).get("pid")
    return live_by_pid().get(pid)


def print_prs(address, fresh=False):
    session = session_of(address)
    if not session:
        return print(json.dumps({"session": None, "ticket": None, "prs": [], "config": sessionlib.PUBLIC_CONFIG}))
    sid = session["sessionId"]
    prs = my_prs(transcript_prs(sid), fresh)
    name = session.get("name") or sid[:8]
    mentioned = pr_tickets([sid]).get(sid, [])
    named = sessionlib.TICKET_RE.search(name)
    order = list(dict.fromkeys(([named.group(1).upper()] if named else []) + mentioned))
    ticket = session_ticket(order[0]) if order else None
    print(json.dumps({"session": name, "id": sid, "ticket": ticket, "prs": prs, "tickets": ticket_tabs(sid, prs, order),
                      "config": sessionlib.PUBLIC_CONFIG}))


def ticket_tabs(session_id, prs, order):
    """One entry per ticket of the session: the ones with a PR in `order`, then PRs without a ticket, then tickets with a branch only."""
    by_ticket = {}
    for pr in prs:
        match = sessionlib.TICKET_RE.search(pr.get("title") or "")
        by_ticket.setdefault(match.group(1).upper() if match else None, []).append(pr["key"])
    keys = [k for k in order if k in by_ticket] + [k for k in by_ticket if k is not None and k not in order]
    tabs = [session_ticket(k) | {"prs": by_ticket[k], "branches": []} for k in keys]
    if None in by_ticket:
        tabs.append({"key": None, "summary": None, "status": None, "category": None, "prs": by_ticket[None], "branches": []})
    for key, branches in branch_tickets(session_id).items():
        if key not in by_ticket:
            tabs.append(session_ticket(key) | {"prs": [], "branches": branches})
    return tabs


def branch_tickets(session_id):
    """Tickets named in the branches the session created or pushed, with those branches."""
    found = {}
    for path in transcripts(session_id):
        with path.open(errors="replace") as fh:
            for line in fh:
                if '"tool_use"' not in line or not sessionlib.TICKET_RE.search(line):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("isSidechain"):
                    continue
                for block in (d.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") != "Bash":
                        continue
                    command = (block.get("input") or {}).get("command") or ""
                    if not sessionlib.BRANCH_CMD_RE.search(command):
                        continue
                    for m in sessionlib.BRANCH_RE.finditer(command):
                        branches = found.setdefault(m.group(1).upper(), [])
                        if m.group(0) not in branches:
                            branches.append(m.group(0))
    return found


def print_failed():
    """Open PRs of mine, across every live Claude session, whose last build failed."""
    keys = []
    for s in live_by_pid().values():
        for k in transcript_prs(s.get("sessionId", "")):
            if k not in keys:
                keys.append(k)
    failed = [p for p in my_prs(keys) if p.get("state") == "OPEN" and p.get("ci") == "failed"]
    print(json.dumps({"failed": failed}))


def print_changes():
    """What happened to my open PRs since the last call: approval, needs work, comment, failed CI, merge.
    A PR seen for the first time is recorded without an event."""
    live = live_by_pid()
    owners = {}
    for t in live_terminals():
        s = live.get((t.get("foreground") or {}).get("pid"))
        for key in transcript_prs(s["sessionId"]) if s else []:
            owners.setdefault(key, t["address"])
    try:
        seen = json.loads(NOTIFIED_STATE.read_text())
    except (OSError, ValueError):
        seen = {}
    events = []
    for pr in my_prs(list(owners)):
        if "approved" not in pr:
            continue
        now = {f: pr[f] for f in ("state", "ci", "approved", "needs_work", "comments")}
        before = seen.get(pr["key"])
        if before == now:
            continue
        if before:
            events += [e | {"terminal": owners[pr["key"]], "url": pr["url"]} for e in pr_events(pr, before, now)]
        seen[pr["key"]] = now
    NOTIFIED_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = NOTIFIED_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen))
    tmp.replace(NOTIFIED_STATE)
    print(json.dumps({"events": events}))


def pr_events(pr, before, now):
    name = f"#{pr['number']}"
    where = pr["repo"]
    if now["state"] != "OPEN":
        merged = before["state"] == "OPEN" and now["state"] == "MERGED"
        return [{"kind": "merged", "title": f"{name} merged", "body": where, "level": "success"}] if merged else []
    events = []
    for who in [u for u in now["needs_work"] if u not in before["needs_work"]]:
        events.append({"kind": "needs_work", "title": f"{name} needs work", "body": f"{where} · {who}", "level": "warning"})
    for who in [u for u in now["approved"] if u not in before["approved"]]:
        events.append({"kind": "approved", "title": f"{name} approved", "body": f"{where} · {who}", "level": "success"})
    if now["comments"] > before["comments"]:
        events.append({"kind": "comment", "title": f"{name} new comment", "body": f"{where} · {pr.get('commenter') or ''}",
                       "level": "info"})
    if now["ci"] == "failed" and before["ci"] != "failed":
        events.append({"kind": "ci", "title": f"{name} CI failed", "body": where, "level": "error"})
    return events


def my_prs(keys, fresh=False):
    cache = read_cache()
    stale = [k for k in keys if fresh or is_stale(cache.get(k))]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for key, info in zip(stale, pool.map(pr_info, stale)):
            if info:
                cache[key] = info | {"at": time.time()}
    if stale:
        write_cache(cache)
    me = sessionlib.stash_user()
    return [cache[k] | {"key": k} for k in keys if me and cache.get(k, {}).get("author") == me]


def print_docs(address):
    session = session_of(address)
    print(json.dumps({"docs": transcript_docs(session["sessionId"]) if session else []}))


def transcripts(session_id):
    return PROJECTS_DIR.glob(f"*/{session_id}.jsonl") if session_id else []


def transcript_docs(session_id):
    """Markdown files the session wrote or edited, most recently touched first, that still exist."""
    touched = {}
    for path in transcripts(session_id):
        with path.open(errors="replace") as fh:
            for line in fh:
                if '"tool_use"' not in line or ".md" not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                for block in (d.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    if block.get("name") not in ("Write", "Edit", "MultiEdit"):
                        continue
                    file = (block.get("input") or {}).get("file_path") or ""
                    if file.endswith(".md"):
                        touched[file] = d.get("timestamp") or ""
    docs = []
    for file, at in sorted(touched.items(), key=lambda kv: kv[1], reverse=True):
        f = Path(file)
        if f.is_file():
            docs.append({"path": file, "name": f.name, "folder": str(f.parent).replace(str(Path.home()), "~", 1), "at": at})
    return docs


def session_ticket(name):
    match = sessionlib.TICKET_RE.search(name)
    if not match:
        return None
    key = match.group(1).upper()
    info = sessionlib.ticket_info(key)
    return {"key": key, "summary": info.get("summary"), "status": info.get("status"), "category": info.get("category")}


def is_stale(entry):
    if not entry:
        return True
    if entry.get("state") == "MERGED":
        return False
    if entry.get("state") == "DECLINED":
        return time.time() - entry.get("at", 0) > PR_TTL_DECLINED
    ttl = PR_TTL_RUNNING if entry.get("ci") == "inprogress" else PR_TTL
    return time.time() - entry.get("at", 0) > ttl


def transcript_prs(session_id):
    keys = []
    for path in transcripts(session_id):
        with path.open(errors="replace") as fh:
            for line in fh:
                for m in sessionlib.PR_RE.finditer(authored_text(line)):
                    key = f"{m.group(1)}/{m.group(2)}#{m.group(3)}"
                    if key not in keys:
                        keys.append(key)
    return keys


def authored_text(line):
    """Text the session itself wrote: prompts, replies, PR links. Tool calls and their output are left out."""
    if "pull-requests/" not in line:
        return ""
    try:
        d = json.loads(line)
    except ValueError:
        return ""
    if d.get("type") == "pr-link":
        return d.get("prUrl") or ""
    if d.get("type") not in ("user", "assistant") or d.get("isSidechain"):
        return ""
    content = (d.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def pr_info(key):
    project, rest = key.split("/", 1)
    repo, number = rest.split("#")
    base = f"{sessionlib.STASH_API}/projects/{project}/repos/{repo}/pull-requests/{number}"
    pr = sessionlib.stash_get(base)
    if not pr:
        return None
    author = pr.get("author", {}).get("user", {}).get("name")
    mine = author == sessionlib.stash_user()
    builds = commit_builds(pr.get("fromRef", {}).get("latestCommit")) if mine else []
    human = sessionlib.human_comments(base) if mine else []
    return {
        "author": author,
        "repo": repo,
        "number": int(number),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "draft": bool(pr.get("draft")),
        "label": sessionlib.review_label(pr, human) if mine else "",
        "approved": sessionlib.reviewers(pr, "APPROVED"),
        "needs_work": sessionlib.reviewers(pr, "NEEDS_WORK"),
        "comments": len(human),
        "commenter": human[0]["user"]["name"] if human else None,
        "ci": ci_state(builds),
        "ci_url": next((b["url"] for b in builds if b["state"] != "SUCCESSFUL"), builds[0]["url"] if builds else None),
        "url": f"{sessionlib.STASH_URL}/projects/{project}/repos/{repo}/pull-requests/{number}",
    }


def commit_builds(sha):
    if not sha:
        return []
    data = sessionlib.stash_get(f"{sessionlib.STASH_URL}/rest/build-status/1.0/commits/{sha}") or {}
    return data.get("values", [])


def ci_state(builds):
    states = {b["state"] for b in builds}
    for state in ("FAILED", "INPROGRESS", "SUCCESSFUL"):
        if state in states:
            return state.lower()
    return "none"


def read_cache():
    try:
        return json.loads(PR_CACHE.read_text())
    except (OSError, ValueError):
        return {}


def write_cache(cache):
    PR_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PR_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(PR_CACHE)


if __name__ == "__main__":
    main()
