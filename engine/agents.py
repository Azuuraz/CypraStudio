from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).with_name("agent_registry.json")
TEMPLATES_PATH = Path(__file__).with_name("agent_templates.json")
CUSTOM_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "custom_specialists.json"
CUSTOM_GROUP_NAME = "My Specialists"
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
_TEMPLATES: list[dict[str, Any]] | None = None
_TEMPLATE_INDEX: dict[str, dict[str, Any]] | None = None
_MAX_CUSTOM_AGENTS = 200
_MAX_PROMPT_CHARS = 7000


def _clean_text(value: Any, maximum: int, *, required: bool = False, field: str = "Field") -> str:
    text = str(value or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > maximum:
        raise ValueError(f"{field} is too long (maximum {maximum} characters)")
    return text


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _load() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load the immutable built-in registry."""
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
                    "prompt": prompt[:_MAX_PROMPT_CHARS],
                    "custom": False,
                })
        except Exception:
            rows = []
        _ROWS = rows
        _INDEX = {row["id"]: row for row in rows}
        return _ROWS, _INDEX


def _load_templates() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    global _TEMPLATES, _TEMPLATE_INDEX
    with _LOCK:
        if _TEMPLATES is not None and _TEMPLATE_INDEX is not None:
            return _TEMPLATES, _TEMPLATE_INDEX
        templates: list[dict[str, Any]] = []
        try:
            payload = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
            incoming = payload.get("templates") if isinstance(payload, dict) else []
            for item in incoming if isinstance(incoming, list) else []:
                if not isinstance(item, dict):
                    continue
                template_id = _clean_text(item.get("id"), 80).lower()
                name = _clean_text(item.get("name"), 120)
                if not template_id or not name:
                    continue
                defaults = item.get("defaults") if isinstance(item.get("defaults"), dict) else {}
                templates.append({
                    "id": template_id,
                    "name": name,
                    "description": _clean_text(item.get("description"), 320),
                    "defaults": {
                        key: _clean_text(defaults.get(key), 2500)
                        for key in ("mission", "tone", "approach", "structure", "output", "advanced_directive")
                    },
                })
        except Exception:
            templates = []
        _TEMPLATES = templates
        _TEMPLATE_INDEX = {item["id"]: item for item in templates}
        return _TEMPLATES, _TEMPLATE_INDEX


def list_templates() -> list[dict[str, Any]]:
    return deepcopy(_load_templates()[0])


def editable_groups() -> list[str]:
    return list(_GROUP_ORDER)


def _load_custom() -> list[dict[str, Any]]:
    with _LOCK:
        if not CUSTOM_REGISTRY_PATH.exists():
            return []
        try:
            payload = json.loads(CUSTOM_REGISTRY_PATH.read_text(encoding="utf-8"))
            incoming = payload.get("agents") if isinstance(payload, dict) else []
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        for item in incoming if isinstance(incoming, list) else []:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("id") or "").strip().lower()
            if not agent_id.startswith("custom-"):
                continue
            row = dict(item)
            row["id"] = agent_id[:120]
            row["custom"] = True
            rows.append(row)
        return rows[:_MAX_CUSTOM_AGENTS]


def _save_custom(rows: list[dict[str, Any]]) -> None:
    _atomic_json(CUSTOM_REGISTRY_PATH, {"version": 1, "agents": rows[:_MAX_CUSTOM_AGENTS]})


def _slug_base(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:90]
    return f"custom-{slug or 'specialist'}"


def _unique_custom_id(name: str, custom_rows: list[dict[str, Any]]) -> str:
    base = _slug_base(name)
    occupied = set(_load()[1]) | {str(item.get("id") or "").lower() for item in custom_rows}
    if base not in occupied:
        return base
    for number in range(2, 10000):
        candidate = f"{base[:110]}-{number}"
        if candidate not in occupied:
            return candidate
    raise ValueError("Could not allocate a unique specialist ID")


def _normalize_payload(payload: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Specialist payload must be an object")
    templates, template_index = _load_templates()
    default_template = templates[0]["id"] if templates else "blank"
    template_id = _clean_text(payload.get("template_id") or (existing or {}).get("template_id") or default_template, 80).lower()
    template = template_index.get(template_id)
    if not template:
        raise ValueError("Unknown specialist template")
    defaults = template.get("defaults") or {}

    group = _clean_text(payload.get("group") or (existing or {}).get("group") or "Specialized & Other", 120, required=True, field="Group")
    if group not in _GROUP_ORDER:
        raise ValueError("Custom specialists must use an existing specialist group")

    def value(name: str, limit: int, required: bool = False, label: str | None = None) -> str:
        raw = payload[name] if name in payload else (existing or {}).get(name, defaults.get(name, ""))
        if (raw is None or str(raw).strip() == "") and name not in payload and not existing:
            raw = defaults.get(name, "")
        return _clean_text(raw, limit, required=required, field=label or name.replace("_", " ").title())

    normalized = {
        "template_id": template_id,
        "name": value("name", 120, True, "Name"),
        "description": value("description", 320, False, "Description"),
        "group": group,
        "mission": value("mission", 1000, True, "Role / mission"),
        "tone": value("tone", 1200, True, "Tone"),
        "approach": value("approach", 1600, True, "Approach"),
        "structure": value("structure", 1600, True, "Structure"),
        "output": value("output", 1600, True, "Output"),
        "advanced_directive": value("advanced_directive", 2500, False, "Advanced directive"),
    }
    if not normalized["description"]:
        normalized["description"] = "Custom Matrix specialist."
    normalized["prompt"] = compile_directive(normalized)
    return normalized


def compile_directive(fields: dict[str, Any]) -> str:
    name = _clean_text(fields.get("name"), 120, required=True, field="Name")
    mission = _clean_text(fields.get("mission"), 1000, required=True, field="Role / mission")
    tone = _clean_text(fields.get("tone"), 1200, required=True, field="Tone")
    approach = _clean_text(fields.get("approach"), 1600, required=True, field="Approach")
    structure = _clean_text(fields.get("structure"), 1600, required=True, field="Structure")
    output = _clean_text(fields.get("output"), 1600, required=True, field="Output")
    advanced = _clean_text(fields.get("advanced_directive"), 2500, field="Advanced directive")
    prompt = (
        f"You are {name}, {mission.rstrip('.')}.\n\n"
        "Operating Rules:\n"
        f"1. Tone: {tone}\n"
        f"2. Approach: {approach}\n"
        f"3. Structure: {structure}\n"
        f"4. Output: {output}"
    )
    if advanced:
        prompt += f"\n\nAdditional Directives:\n{advanced}"
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ValueError(f"Compiled directive is too long (maximum {_MAX_PROMPT_CHARS} characters)")
    return prompt


def create_custom_agent(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        rows = _load_custom()
        if len(rows) >= _MAX_CUSTOM_AGENTS:
            raise ValueError(f"Custom specialist limit reached ({_MAX_CUSTOM_AGENTS})")
        normalized = _normalize_payload(payload)
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": _unique_custom_id(normalized["name"], rows),
            **normalized,
            "custom": True,
            "created_at": now,
            "updated_at": now,
        }
        rows.append(row)
        _save_custom(rows)
        return deepcopy(row)


def get_custom_agent(agent_id: str | None) -> dict[str, Any] | None:
    slug = str(agent_id or "").strip().lower()
    if not slug:
        return None
    for row in _load_custom():
        if row.get("id") == slug:
            return deepcopy(row)
    return None


def update_custom_agent(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    slug = str(agent_id or "").strip().lower()
    with _LOCK:
        rows = _load_custom()
        for index, row in enumerate(rows):
            if row.get("id") != slug:
                continue
            normalized = _normalize_payload(payload, existing=row)
            updated = {
                **row,
                **normalized,
                "id": slug,
                "custom": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            rows[index] = updated
            _save_custom(rows)
            return deepcopy(updated)
    if slug in _load()[1]:
        raise ValueError("Built-in specialists are read-only")
    raise KeyError("Custom specialist not found")


def duplicate_custom_agent(agent_id: str) -> dict[str, Any]:
    row = get_custom_agent(agent_id)
    if not row:
        if str(agent_id or "").strip().lower() in _load()[1]:
            raise ValueError("Built-in specialists cannot be duplicated through the custom editor")
        raise KeyError("Custom specialist not found")
    payload = {key: row.get(key, "") for key in (
        "template_id", "name", "description", "group", "mission", "tone", "approach", "structure", "output", "advanced_directive"
    )}
    payload["name"] = f"{row['name']} Copy"[:120]
    return create_custom_agent(payload)


def delete_custom_agent(agent_id: str) -> bool:
    slug = str(agent_id or "").strip().lower()
    with _LOCK:
        rows = _load_custom()
        next_rows = [row for row in rows if row.get("id") != slug]
        if len(next_rows) != len(rows):
            _save_custom(next_rows)
            return True
    if slug in _load()[1]:
        raise ValueError("Built-in specialists are read-only")
    raise KeyError("Custom specialist not found")


def registry_count() -> int:
    return len(_load()[0]) + len(_load_custom())


def list_groups() -> list[dict[str, Any]]:
    builtins, _ = _load()
    custom = _load_custom()
    counts: dict[str, int] = {name: 0 for name in _GROUP_ORDER}
    for row in [*builtins, *custom]:
        group = row.get("group") if row.get("group") in counts else "Specialized & Other"
        counts[str(group)] += 1
    groups: list[dict[str, Any]] = []
    if custom:
        groups.append({"id": CUSTOM_GROUP_NAME, "name": CUSTOM_GROUP_NAME, "count": len(custom), "custom": True})
    groups.extend({"id": name, "name": name, "count": counts[name], "custom": False} for name in _GROUP_ORDER if counts[name])
    return groups


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "group": row["group"],
        "custom": bool(row.get("custom")),
    }


def list_agents(group: str | None = None, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    builtins, _ = _load()
    custom = _load_custom()
    rows = custom if str(group or "").strip() == CUSTOM_GROUP_NAME else [*builtins, *custom]
    group_key = str(group or "").strip()
    query = " ".join(str(search or "").lower().split())
    result: list[dict[str, Any]] = []
    max_limit = max(1, min(1000, int(limit or 200)))
    for row in rows:
        if group_key and group_key != CUSTOM_GROUP_NAME and row.get("group") != group_key:
            continue
        hay = f"{row.get('id','')} {row.get('name','')} {row.get('description','')} {row.get('group','')}".lower()
        if query and query not in hay:
            terms = query.split()
            if not all(term in hay for term in terms):
                continue
        result.append(_public_row(row))
        if len(result) >= max_limit:
            break
    return result


def get_agent(agent_id: str | None) -> dict[str, Any] | None:
    slug = str(agent_id or "").strip().lower()
    if not slug:
        return None
    custom = get_custom_agent(slug)
    if custom:
        return custom
    return _load()[1].get(slug)


def prompt_for(agent_id: str | None) -> str:
    row = get_agent(agent_id)
    return str(row.get("prompt") or "") if row else ""


def public_agent(agent_id: str | None) -> dict[str, Any] | None:
    row = get_agent(agent_id)
    if not row:
        return None
    return _public_row(row)
