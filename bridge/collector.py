"""Live Orca + Cursor agent snapshot for VibeOS."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("USERPROFILE", str(Path.home())))
CURSOR_HOME = HOME / ".cursor"
CURSOR_IDE_STATE = CURSOR_HOME / "ide_state.json"
CURSOR_PROJECTS = CURSOR_HOME / "projects"
ORCA = "orca"

WORKING_STATES = {
    "working",
    "running",
    "thinking",
    "streaming",
    "in-progress",
    "in_progress",
    "tool",
    "active",
}
ATTENTION_STATES = {
    "waiting",
    "wait",
    "ask",
    "needs-input",
    "needs_input",
    "blocked",
    "error",
    "failed",
}
ENDED_STATES = {
    "done",
    "completed",
    "idle",
    "stopped",
    "exited",
    "interrupted",
}

IDLE_MARKERS = (
    "[stable]",
    "resume session",
    "turn completed",
    "start grok in a fresh",
)
SHELL_RE = re.compile(
    r"(@[\w.-]+\s+\S+\s+[%$#])|(cristian@)|(❯\s*%)|(^%\s*$)",
    re.I | re.M,
)
IDLE_PROMPT_RE = re.compile(
    r"(│\s*[❯>]\s*(build anything)?\s*│)|([❯>]\s{4,})|(│\s*[❯>]\s*$)",
    re.I | re.M,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _run_json(args: list[str], timeout: float = 10.0) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start < 0:
            return None
        try:
            payload = json.loads(raw[start:])
        except json.JSONDecodeError:
            return None
    if isinstance(payload, dict) and payload.get("ok") is False:
        return None
    return payload


def _result(payload: dict[str, Any] | None) -> Any:
    if not payload:
        return None
    if payload.get("ok") and "result" in payload:
        return payload["result"]
    return payload


def _orca(args: list[str], env: str | None = None) -> Any:
    cmd = [ORCA]
    if env:
        cmd += ["--environment", env]
    cmd += args
    return _result(_run_json(cmd))


def orca_source() -> str:
    explicit = (os.environ.get("VIBEOS_ORCA_SOURCE") or "").strip()
    if explicit:
        return explicit
    if platform.system() == "Darwin":
        return "local"
    return "Mac Mini"


def _environments() -> list[str | None]:
    source = orca_source()
    if source.lower() in {"local", "darwin", "this"}:
        return [None]
    return [source]


def _host_snapshots() -> list[tuple[str, Any, Any]]:
    envs = _environments()

    def one(env: str | None) -> tuple[str, Any, Any]:
        label = env or "local"
        ps = _orca(["worktree", "ps", "--json"], env)
        terms = _orca(["terminal", "list", "--json"], env)
        return label, ps, terms

    out: list[tuple[str, Any, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(one, env) for env in envs]
        for fut in as_completed(futs):
            try:
                out.append(fut.result())
            except Exception:
                continue
    return out


def _classify_terminal(term: dict[str, Any]) -> str | None:
    if not term.get("agentIdentity"):
        return None
    if not term.get("connected"):
        return "ended"
    preview = str(term.get("preview") or "")
    low = preview.lower()
    if term.get("agentWait"):
        return "attention"
    if any(tok in low for tok in ("need you", "waiting for permission", "ask the user")):
        return "attention"
    if SHELL_RE.search(preview) and "grok 4" not in low:
        return None
    idle = any(m in low for m in IDLE_MARKERS) or bool(IDLE_PROMPT_RE.search(preview))
    last = term.get("lastOutputAt")
    age_s = None
    if isinstance(last, (int, float)) and last > 0:
        age_s = (_now_ms() - last) / 1000.0
    if idle:
        return "ended"
    if age_s is not None and age_s < 20:
        return "working"
    if age_s is not None and age_s < 90 and any(
        tok in low for tok in ("thinking", "tool", "running", "worked for", "in progress")
    ):
        return "working"
    return "ended"


def _classify_agent(agent: dict[str, Any], unread: bool) -> str:
    state = str(agent.get("state") or "").lower()
    if unread and state in ENDED_STATES:
        return "attention"
    if state in ATTENTION_STATES or agent.get("interrupted"):
        return "attention"
    if state in WORKING_STATES:
        return "working"
    if state in ENDED_STATES:
        return "ended"
    return "ended"


def collect_orca() -> dict[str, Any]:
    working_items: list[dict[str, Any]] = []
    ended_items: list[dict[str, Any]] = []
    attention_items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(status: str, item: dict[str, Any]) -> None:
        key = str(item.get("id") or "")
        if not key or key in seen:
            return
        seen.add(key)
        if status == "working":
            working_items.append(item)
        elif status == "attention":
            attention_items.append(item)
        else:
            ended_items.append(item)

    hosts = _host_snapshots()
    available = bool(hosts)
    for host, ps, terms in hosts:
        worktrees = []
        if isinstance(ps, dict):
            worktrees = ps.get("worktrees") or []
        terminals = []
        if isinstance(terms, dict):
            terminals = terms.get("terminals") or []

        covered_panes: set[str] = set()
        for wt in worktrees:
            unread = bool(wt.get("unread"))
            repo = wt.get("repo") or Path(str(wt.get("path") or "")).name
            for agent in wt.get("agents") or []:
                pane = str(agent.get("paneKey") or "")
                aid = f"{host}:{pane or agent.get('updatedAt') or repo}"
                covered_panes.add(pane)
                item = {
                    "kind": "agent",
                    "id": aid,
                    "name": agent.get("taskTitle")
                    or (str(agent.get("prompt") or "")[:48] or repo),
                    "agent": agent.get("agentType") or agent.get("displayName"),
                    "worktree": repo,
                    "host": host,
                    "state": agent.get("state"),
                    "unread": unread,
                }
                add(_classify_agent(agent, unread), item)

        for term in terminals:
            tab = term.get("tabId") or ""
            leaf = term.get("leafId") or ""
            pane = f"{tab}:{leaf}" if tab and leaf else ""
            if pane and pane in covered_panes:
                continue
            status = _classify_terminal(term)
            if not status:
                continue
            handle = str(term.get("handle") or pane)
            item = {
                "kind": "terminal",
                "id": f"{host}:{handle}",
                "name": term.get("title") or term.get("agentIdentity"),
                "agent": term.get("agentIdentity"),
                "worktree": Path(str(term.get("worktreePath") or "")).name,
                "host": host,
                "preview": (term.get("preview") or "")[-120:],
            }
            add(status, item)

    return {
        "available": available,
        "working": len(working_items),
        "ended": len(ended_items),
        "attention": len(attention_items),
        "ids": {
            "working": [i["id"] for i in working_items],
            "ended": [i["id"] for i in ended_items],
            "attention": [i["id"] for i in attention_items],
        },
        "items": {
            "working": working_items[:8],
            "ended": ended_items[:8],
            "attention": attention_items[:8],
        },
        "terminals": [
            {"title": i.get("name"), "agent": i.get("agent"), "host": i.get("host")}
            for i in working_items
        ],
    }


def _cursor_running() -> dict[str, Any]:
    running = False
    pids: list[int] = []
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process Cursor,cursor -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        running = bool(pids)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"running": running, "pids": pids[:12]}


def _cursor_file() -> str | None:
    try:
        data = json.loads(CURSOR_IDE_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    files = data.get("recentlyViewedFiles") or []
    if not files:
        return None
    path = files[0].get("absolutePath") or files[0].get("relativePath")
    return str(path) if path else None


def _last_jsonl(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 8000))
            chunk = fh.read().decode("utf-8", "replace")
        line = [ln for ln in chunk.splitlines() if ln.strip()][-1]
        return json.loads(line)
    except (OSError, json.JSONDecodeError, IndexError):
        return None


def _cursor_agents() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not CURSOR_PROJECTS.exists():
        return items
    cutoff = time.time() - 15 * 60
    for project in CURSOR_PROJECTS.iterdir():
        transcripts = project / "agent-transcripts"
        if not transcripts.is_dir():
            continue
        for path in transcripts.glob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            last = _last_jsonl(path)
            status = "ended"
            age = time.time() - mtime
            if last:
                kind = str(last.get("type") or last.get("role") or "").lower()
                if last.get("error"):
                    status = "attention"
                elif kind in {"assistant", "thinking", "tool_call", "tool"} and age < 90:
                    status = "working"
            elif age < 45:
                status = "working"
            items.append(
                {
                    "kind": "cursor",
                    "id": f"cursor:{path.stem}",
                    "project": project.name[-24:],
                    "name": path.stem[:10],
                    "status": status,
                    "age_s": int(age),
                }
            )
    items.sort(key=lambda x: x["age_s"])
    return items[:12]


def collect_cursor() -> dict[str, Any]:
    proc = _cursor_running()
    agents = _cursor_agents() if proc["running"] else []
    working = [a for a in agents if a["status"] == "working"]
    ended = [a for a in agents if a["status"] == "ended"]
    attention = [a for a in agents if a["status"] == "attention"]
    current = _cursor_file()
    return {
        "running": proc["running"],
        "pids": proc["pids"],
        "file": current,
        "file_name": Path(current).name if current else None,
        "working": len(working),
        "ended": len(ended),
        "attention": len(attention),
        "agents": agents,
    }


def snapshot() -> dict[str, Any]:
    orca = collect_orca()
    return {
        "ts": _now_ms(),
        "source": orca_source(),
        "working": orca["working"],
        "ended": orca["ended"],
        "attention": orca["attention"],
        "ids": orca.get("ids") or {"working": [], "ended": [], "attention": []},
        "orca": orca,
        "cursor": {
            "running": False,
            "working": 0,
            "ended": 0,
            "attention": 0,
            "agents": [],
        },
    }
