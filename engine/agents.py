from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).with_name("agent_registry.json")
_GROUP_ORDER = [
    "AI & Computing",
    "Security",
    "Networking & Infrastructure",
    "Data & Analytics",
    "Science & Medicine",
    "Engineering & Hardware",
    "Business & Operations",
    "Finance & Economics",
    "Legal & Governance",
    "Creative & Design",
    "Education & Humanities",
    "Specialized & Other",
]
_LOCK = threading.RLock()
_ROWS: list[dict[str, Any]] | None = None
_INDEX: dict[str, dict[str, Any]] | None = None


def _load() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    global _ROWS, _INDEX
    with _LOCK:
        if _ROWS is not None and _INDEX is not None:
            return _ROWS, _INDEX
        rows: list[dict[str, Any]] = []
        try:
            payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            incoming = payload.get("agents") if isinstance(payload, dict) else []
            for item in incoming if isinstance(incoming, list) else []:
                if not isinstance(item, dict):
                    continue
                slug = str(item.get("id") or "").strip().lower()
                prompt = str(item.get("prompt") or "").strip()
                if not slug or not prompt:
                    continue
                rows.append({
                    "id": slug,
                    "name": str(item.get("name") or slug.replace("-", " ").title())[:120],
                    "description": str(item.get("description") or "Matrix specialist.")[:320],
                    "group": str(item.get("group") or "Specialized & Other"),
                    "prompt": prompt[:7000],
                })
        except Exception:
            rows = []
        _ROWS = rows
        _INDEX = {row["id"]: row for row in rows}
        return _ROWS, _INDEX


def registry_count() -> int:
    return len(_load()[0])


def list_groups() -> list[dict[str, Any]]:
    rows, _ = _load()
    counts: dict[str, int] = {name: 0 for name in _GROUP_ORDER}
    for row in rows:
        group = row.get("group") if row.get("group") in counts else "Specialized & Other"
        counts[str(group)] += 1
    return [{"id": name, "name": name, "count": counts[name]} for name in _GROUP_ORDER if counts[name]]


def list_agents(group: str | None = None, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows, _ = _load()
    group_key = str(group or "").strip()
    query = " ".join(str(search or "").lower().split())
    result: list[dict[str, Any]] = []
    for row in rows:
        if group_key and row.get("group") != group_key:
            continue
        hay = f"{row.get('id','')} {row.get('name','')} {row.get('description','')}".lower()
        if query and query not in hay:
            terms = query.split()
            if not all(term in hay for term in terms):
                continue
        result.append({
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "group": row["group"],
        })
        if len(result) >= max(1, min(700, int(limit or 200))):
            break
    return result


def get_agent(agent_id: str | None) -> dict[str, Any] | None:
    slug = str(agent_id or "").strip().lower()
    if not slug:
        return None
    return _load()[1].get(slug)


def prompt_for(agent_id: str | None) -> str:
    row = get_agent(agent_id)
    return str(row.get("prompt") or "") if row else ""


def public_agent(agent_id: str | None) -> dict[str, Any] | None:
    row = get_agent(agent_id)
    if not row:
        return None
    return {k: row[k] for k in ("id", "name", "description", "group")}
