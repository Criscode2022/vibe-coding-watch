"""Live Orca + Cursor agent snapshot for VibeOS."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("USERPROFILE", str(Path.home())))
CURSOR_HOME = HOME / ".cursor"
CURSOR_IDE_STATE = CURSOR_HOME / "ide_state.json"
CURSOR_PROJECTS = CURSOR_HOME / "projects"
ORCA = "orca"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _run_json(args: list[str], timeout: float = 8.0) -> dict[str, Any] | None:
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
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start < 0:
            return None
        try:
            return json.loads(raw[start:])
        except json.JSONDecodeError:
            return None


def _result(payload: dict[str, Any] | None) -> Any:
    if not payload:
        return None
    if payload.get("ok") and "result" in payload:
        return payload["result"]
    return payload


def _item_key(item: dict[str, Any]) -> str:
    return "|".join(
        str(item.get(k) or "")
        for k in ("kind", "agent", "name", "worktree", "id", "project")
    )


def _looks_blocked(text: str) -> bool:
    t = (text or "").lower()
    return any(
        token in t
        for token in (
            "error",
            "failed",
            "blocked",
            "need you",
            "waiting for",
            "permission",
            "conflict",
            "attention",
        )
    )


def collect_orca() -> dict[str, Any]:
    ps = _result(_run_json([ORCA, "worktree", "ps", "--json"]))
    terms = _result(_run_json([ORCA, "terminal", "list", "--json"]))
    workers = _result(_run_json([ORCA, "orchestration", "worker-list", "--json"]))
    tasks = _result(_run_json([ORCA, "orchestration", "task-list", "--json"]))

    worktrees = []
    if isinstance(ps, dict):
        worktrees = ps.get("worktrees") or []
    elif isinstance(ps, list):
        worktrees = ps

    terminals = []
    if isinstance(terms, dict):
        terminals = terms.get("terminals") or []
    elif isinstance(terms, list):
        terminals = terms

    agent_terms = [t for t in terminals if t.get("connected") and t.get("agentIdentity")]
    working_items: list[dict[str, Any]] = []
    ended_items: list[dict[str, Any]] = []
    attention_items: list[dict[str, Any]] = []

    for term in agent_terms:
        item = {
            "kind": "terminal",
            "id": str(term.get("handle") or term.get("title") or ""),
            "name": term.get("title") or term.get("agentIdentity"),
            "agent": term.get("agentIdentity"),
            "worktree": Path(str(term.get("worktreePath") or "")).name,
            "preview": (term.get("preview") or "")[-160:],
        }
        if _looks_blocked(str(term.get("preview") or "")):
            attention_items.append(item)
        else:
            working_items.append(item)

    seen_active = {t.get("worktreeId") for t in agent_terms}
    for wt in worktrees:
        status = (wt.get("workspaceStatus") or "").lower()
        live = int(wt.get("liveTerminalCount") or 0)
        name = wt.get("displayName") or wt.get("repo") or "worktree"
        item = {
            "kind": "worktree",
            "name": name,
            "repo": wt.get("repo"),
            "status": status,
            "live": live,
            "comment": wt.get("comment") or "",
            "preview": (wt.get("preview") or "")[-160:],
        }
        if wt.get("unread") or status in {"in-review", "blocked"} or _looks_blocked(item["comment"]):
            attention_items.append(item)
        elif status == "completed":
            ended_items.append(item)
        elif live > 0 or wt.get("status") == "active" or wt.get("worktreeId") in seen_active:
            if not any(w.get("worktree") == Path(str(wt.get("path") or "")).name for w in working_items):
                working_items.append(item)

    if isinstance(workers, dict):
        rows = workers.get("workers") or workers.get("items") or []
        for row in rows:
            st = str(row.get("status") or row.get("state") or "").lower()
            item = {"kind": "worker", "name": row.get("title") or row.get("id"), "status": st}
            if st in {"failed", "blocked", "needs-attention", "error"}:
                attention_items.append(item)
            elif st in {"running", "active", "working"}:
                working_items.append(item)
            elif st in {"done", "completed", "stopped", "exited"}:
                ended_items.append(item)

    if isinstance(tasks, dict):
        rows = tasks.get("tasks") or tasks.get("items") or []
        for row in rows:
            st = str(row.get("status") or "").lower()
            item = {"kind": "task", "name": row.get("title") or row.get("id"), "status": st}
            if st in {"blocked", "failed", "needs-attention"}:
                attention_items.append(item)
            elif st in {"running", "in-progress", "dispatched"}:
                working_items.append(item)
            elif st in {"done", "completed"}:
                ended_items.append(item)

    return {
        "available": ps is not None or terms is not None,
        "working": len(working_items),
        "ended": len(ended_items),
        "attention": len(attention_items),
        "ids": {
            "working": [_item_key(i) for i in working_items],
            "ended": [_item_key(i) for i in ended_items],
            "attention": [_item_key(i) for i in attention_items],
        },
        "items": {
            "working": working_items[:8],
            "ended": ended_items[:8],
            "attention": attention_items[:8],
        },
        "terminals": [
            {
                "title": t.get("title"),
                "agent": t.get("agentIdentity"),
                "connected": t.get("connected"),
            }
            for t in agent_terms
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


def _cursor_agents() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not CURSOR_PROJECTS.exists():
        return items
    cutoff = time.time() - 6 * 3600
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
            if last:
                kind = str(last.get("type") or last.get("role") or "").lower()
                if kind in {"assistant", "thinking", "tool_call", "tool"}:
                    if time.time() - mtime < 120:
                        status = "working"
                if last.get("error") or "ask" in kind:
                    status = "attention"
            if time.time() - mtime < 90:
                status = "working"
            items.append(
                {
                    "project": project.name[-24:],
                    "id": path.stem[:10],
                    "status": status,
                    "age_s": int(time.time() - mtime),
                }
            )
    items.sort(key=lambda x: x["age_s"])
    return items[:12]


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


def collect_cursor() -> dict[str, Any]:
    proc = _cursor_running()
    agents = _cursor_agents()
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
    cursor = collect_cursor()
    working = orca["working"] + cursor["working"] + (1 if cursor["running"] and not cursor["agents"] else 0)
    ended = orca["ended"] + cursor["ended"]
    attention = orca["attention"] + cursor["attention"]
    cursor_ids = {
        "working": [_item_key(a) for a in cursor["agents"] if a["status"] == "working"],
        "ended": [_item_key(a) for a in cursor["agents"] if a["status"] == "ended"],
        "attention": [_item_key(a) for a in cursor["agents"] if a["status"] == "attention"],
    }
    orca_ids = orca.get("ids") or {"working": [], "ended": [], "attention": []}
    return {
        "ts": _now_ms(),
        "working": working,
        "ended": ended,
        "attention": attention,
        "ids": {
            "working": orca_ids.get("working", []) + cursor_ids["working"],
            "ended": orca_ids.get("ended", []) + cursor_ids["ended"],
            "attention": orca_ids.get("attention", []) + cursor_ids["attention"],
        },
        "orca": orca,
        "cursor": cursor,
    }
