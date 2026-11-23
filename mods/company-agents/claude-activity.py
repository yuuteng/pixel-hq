#!/usr/bin/env python3
"""Report Claude Code's running shell commands and sub-agents to its Herdr desk.

Writes the same terminal labels Pixel HQ's Hermes plugin writes, so the office shows
runners and LEDs for shell commands and interns for sub-agents:
  agent.jobs          Bash commands in flight
  agent.jobs_started  their start times (ms since epoch, oldest first), so Pixel HQ can
                      turn a job amber after a minute without this hook running again
  agent.threads       sub-agents running

Usage (from Claude Code hooks, JSON on stdin):
  claude-activity.py job-start | job-end | sub-start | sub-end | turn-end | reset
Does nothing outside a Herdr terminal (no HC_TERMINAL_ID) and never fails the hook.

Setup (merges into ~/.claude/settings.json, keeps your other hooks, backs it up first):
  python3 claude-activity.py install      add the hooks (safe to run again)
  python3 claude-activity.py uninstall    remove only the hooks this script added
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time

STALE_JOB_MS = 2 * 3600 * 1000       # a command missing its end event is dropped after 2h
STALE_SUB_MS = 6 * 3600 * 1000       # a sub-agent missing its stop event after 6h
MAX_STARTED = 20


HOOKS = [  # (event, matcher, action)
    ("PreToolUse", "Bash", "job-start"),
    ("PostToolUse", "Bash", "job-end"),
    ("PostToolUseFailure", "Bash", "job-end"),
    ("SubagentStart", None, "sub-start"),
    ("SubagentStop", None, "sub-end"),
    ("UserPromptSubmit", None, "turn-end"),
    ("Stop", None, "turn-end"),
    ("SessionStart", "^(startup|resume|clear)$", "reset"),
    ("SessionEnd", None, "reset"),
]


def setup(remove: bool) -> None:
    path = os.path.expanduser("~/.claude/settings.json")
    try:
        with open(path) as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        cfg = {}
    if not isinstance(cfg, dict):
        sys.exit(f"{path} is not a JSON object; left untouched")
    if os.path.exists(path) and not os.path.exists(path + ".pixel-hq.bak"):
        shutil.copy2(path, path + ".pixel-hq.bak")  # keeps the very first original
    me = os.path.abspath(__file__)
    mark = "claude-activity.py"
    hooks = cfg.setdefault("hooks", {})
    for event, matcher, action in HOOKS:
        groups = hooks.setdefault(event, [])
        for g in groups:  # drop our earlier entries (also makes install idempotent)
            g["hooks"] = [h for h in g.get("hooks", []) if mark not in h.get("command", "")]
        groups[:] = [g for g in groups if g.get("hooks")]
        if not remove:
            group = {"hooks": [{"type": "command", "command": f'python3 -I "{me}" {action}'}]}
            if matcher:
                group["matcher"] = matcher
            groups.append(group)
        if not groups:
            del hooks[event]
    if not hooks:
        del cfg["hooks"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(("Removed" if remove else "Installed") + f" Pixel HQ hooks in {path} (backup: {path}.pixel-hq.bak)")


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action in ("install", "uninstall"):
        return setup(action == "uninstall")
    term = os.environ.get("HC_TERMINAL_ID", "")
    if not action or not term or not term.replace("-", "").isalnum():
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    hc = shutil.which("hc") or os.path.expanduser("~/.local/bin/hc")
    if not os.path.exists(hc):
        return

    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache")
    folder = os.path.join(base, "hc-desk-activity")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, f"{term}.json")
    now = int(time.time() * 1000)

    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            state = json.loads(fh.read() or "{}")
        except Exception:
            state = {}
        jobs = state.get("jobs", {})
        subs = state.get("subs", {})
        last = state.get("last")

        tool_id = str(payload.get("tool_use_id") or "")
        agent_id = str(payload.get("agent_id") or "")
        if action == "job-start" and tool_id:
            jobs[tool_id] = now
        elif action == "job-end" and tool_id:
            jobs.pop(tool_id, None)
        elif action == "sub-start":
            subs[agent_id or f"anon-{now}"] = now
        elif action == "sub-end":
            if agent_id and agent_id in subs:
                subs.pop(agent_id)
            elif subs:  # no id given: retire the oldest
                subs.pop(min(subs, key=subs.get))
        elif action == "turn-end":
            jobs = {}  # foreground commands are all over when a turn ends; sub-agents may run on
        elif action == "reset":
            jobs, subs = {}, {}

        jobs = {k: v for k, v in jobs.items() if now - v < STALE_JOB_MS}
        subs = {k: v for k, v in subs.items() if now - v < STALE_SUB_MS}
        started = sorted(jobs.values())[:MAX_STARTED]
        labels = {
            "agent.jobs": str(len(jobs)),
            "agent.jobs_started": ",".join(str(s) for s in started),
            "agent.threads": str(len(subs)),
        }
        if labels != last:
            try:
                # fire and forget: the hook must not wait on Herdr (a later event fixes any lost label)
                subprocess.Popen([hc, "label", term, *(f"{k}={v}" for k, v in labels.items())],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                last = labels
            except Exception:
                pass

        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"jobs": jobs, "subs": subs, "last": last}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
