from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
KNOWLEDGE_DIR = ROOT / "Knowledge"
SESSIONS_DIR = DATA / "sessions"
DB_PATH = DATA / "retrieval" / "index.sqlite3"

_ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".ps1", ".bat", ".ini", ".cfg"}
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_FILES = 200
_CHUNK_CHARS = 1200
_CHUNK_OVERLAP = 160
_SYNC_INTERVAL = 10.0
_LOCK = threading.RLock()
_SYNC_STATE: dict[str, Any] = {"db": "", "signature": None, "ts": 0.0, "counts": {"knowledge_chunks": 0, "conversation_chunks": 0, "total_chunks": 0}}
_CHAT_SYNC_STATE: dict[str, Any] = {"db": "", "signature": None, "ts": 0.0}

_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "what", "when", "where", "which", "who", "why", "how",
    "are", "was", "were", "been", "being", "have", "has", "had", "does", "did", "can", "could", "would", "should",
    "into", "about", "your", "you", "our", "their", "they", "them", "then", "than", "there", "here", "just", "like",
    "use", "using", "used", "tell", "please", "need", "want", "will", "its", "it's", "a", "an", "to", "of", "in",
    "on", "at", "is", "it", "be", "or", "as", "by", "we", "i", "me", "my", "do", "so", "if", "not",
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5(
            source_type UNINDEXED,
            source_key UNINDEXED,
            label UNINDEXED,
            ordinal UNINDEXED,
            message_index UNINDEXED,
            mtime_ns UNINDEXED,
            size_bytes UNINDEXED,
            content,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )
    return conn


def _terms(query: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9_:\-.]{3,}", str(query or "").lower())
    out: list[str] = []
    for token in raw:
        token = token.strip("-_.:")
        if not token or token in _STOPWORDS or (token.isdigit() and len(token) < 4):
            continue
        if token not in out:
            out.append(token)
    return out[:12]


def _specific_enough(terms: list[str]) -> bool:
    if len(terms) >= 2:
        return True
    return bool(terms and len(terms[0]) >= 7)


def _chunk_text(text: str) -> list[str]:
    clean = str(text or "").replace("\x00", " ").strip()
    if not clean:
        return []
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", clean) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [re.sub(r"\s+", " ", clean)]:
        if len(paragraph) > _CHUNK_CHARS:
            if current:
                chunks.append(current[:_CHUNK_CHARS])
                current = ""
            start = 0
            while start < len(paragraph):
                piece = paragraph[start:start + _CHUNK_CHARS].strip()
                if piece:
                    chunks.append(piece)
                if start + _CHUNK_CHARS >= len(paragraph):
                    break
                start += max(1, _CHUNK_CHARS - _CHUNK_OVERLAP)
            continue
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= _CHUNK_CHARS:
            current = candidate
        else:
            if current:
                chunks.append(current)
            tail = current[-_CHUNK_OVERLAP:] if current else ""
            current = (tail + "\n\n" + paragraph).strip() if tail else paragraph
    if current:
        chunks.append(current[:_CHUNK_CHARS])
    return chunks


def _delete_source(conn: sqlite3.Connection, source_key: str) -> None:
    conn.execute("DELETE FROM entries WHERE source_key = ?", (source_key,))


def _insert_chunks(
    conn: sqlite3.Connection,
    *,
    source_type: str,
    source_key: str,
    label: str,
    text: str,
    mtime_ns: int = 0,
    size_bytes: int = 0,
    message_index: int = -1,
) -> int:
    count = 0
    for ordinal, chunk in enumerate(_chunk_text(text)):
        conn.execute(
            "INSERT INTO entries(source_type, source_key, label, ordinal, message_index, mtime_ns, size_bytes, content) VALUES(?,?,?,?,?,?,?,?)",
            (source_type, source_key, label, ordinal, message_index, mtime_ns, size_bytes, chunk),
        )
        count += 1
    return count


def _knowledge_signature() -> tuple[tuple[str, int, int], ...]:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, int, int]] = []
    for path in sorted(KNOWLEDGE_DIR.rglob("*")):
        if len(rows) >= _MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size <= 0 or stat.st_size > _MAX_FILE_BYTES:
            continue
        rows.append((path.relative_to(KNOWLEDGE_DIR).as_posix(), int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(rows)


def sync_knowledge(*, force: bool = False) -> dict[str, int]:
    with _LOCK:
        now = time.time()
        db_key = str(DB_PATH.resolve())
        if (
            not force
            and _SYNC_STATE.get("db") == db_key
            and now - float(_SYNC_STATE.get("ts") or 0.0) < _SYNC_INTERVAL
        ):
            return dict(_SYNC_STATE.get("counts") or {"knowledge_chunks": 0, "total_chunks": 0})
        signature = _knowledge_signature()
        if not force and _SYNC_STATE.get("db") == db_key and _SYNC_STATE.get("signature") == signature:
            counts = status_counts()
            _SYNC_STATE.update({"ts": now, "counts": counts})
            return counts
        if not signature and not DB_PATH.exists():
            counts = {"knowledge_chunks": 0, "total_chunks": 0}
            _SYNC_STATE.update({"db": db_key, "signature": signature, "ts": now, "counts": counts})
            return counts
        conn = _connect()
        try:
            current_keys = {"knowledge:" + rel for rel, _, _ in signature}
            existing = {str(row[0]) for row in conn.execute("SELECT DISTINCT source_key FROM entries WHERE source_type='knowledge'")}
            for stale in existing - current_keys:
                _delete_source(conn, stale)
            for rel, mtime_ns, size_bytes in signature:
                key = "knowledge:" + rel
                row = conn.execute(
                    "SELECT mtime_ns, size_bytes FROM entries WHERE source_key=? LIMIT 1", (key,)
                ).fetchone()
                if row and int(row["mtime_ns"] or 0) == mtime_ns and int(row["size_bytes"] or 0) == size_bytes:
                    continue
                _delete_source(conn, key)
                path = KNOWLEDGE_DIR / rel
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                _insert_chunks(
                    conn,
                    source_type="knowledge",
                    source_key=key,
                    label=rel,
                    text=text,
                    mtime_ns=mtime_ns,
                    size_bytes=size_bytes,
                )
            conn.commit()
        finally:
            conn.close()
        counts = status_counts()
        _SYNC_STATE.update({"db": db_key, "signature": signature, "ts": now, "counts": counts})
        return counts



def _session_signature() -> tuple[tuple[str, int, int], ...]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, int, int]] = []
    for path in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size <= 0:
            continue
        rows.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(rows)


def sync_sessions(*, force: bool = False) -> dict[str, int]:
    """Incrementally index saved conversations for cross-chat retrieval.

    Only session files whose size/mtime changed are parsed and rewritten. A
    deleted session is removed from the FTS table on the next sync.
    """
    with _LOCK:
        signature = _session_signature()
        db_key = str(DB_PATH.resolve())
        if not force and _CHAT_SYNC_STATE.get("db") == db_key and _CHAT_SYNC_STATE.get("signature") == signature:
            return status_counts()
        if not signature and not DB_PATH.exists():
            _CHAT_SYNC_STATE.update({"db": db_key, "signature": signature, "ts": time.time()})
            return {"knowledge_chunks": 0, "conversation_chunks": 0, "total_chunks": 0}

        conn = _connect()
        try:
            current_keys = {"conversation:" + Path(name).stem for name, _, _ in signature}
            existing = {
                str(row[0])
                for row in conn.execute("SELECT DISTINCT source_key FROM entries WHERE source_type='conversation'")
            }
            for stale in existing - current_keys:
                _delete_source(conn, stale)

            for name, mtime_ns, size_bytes in signature:
                sid = Path(name).stem
                key = "conversation:" + sid
                row = conn.execute(
                    "SELECT mtime_ns, size_bytes FROM entries WHERE source_key=? LIMIT 1", (key,)
                ).fetchone()
                if row and int(row["mtime_ns"] or 0) == mtime_ns and int(row["size_bytes"] or 0) == size_bytes:
                    continue
                _delete_source(conn, key)
                path = SESSIONS_DIR / name
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                title = " ".join(str(payload.get("title") or "Chat").split())[:120] or "Chat"
                stamp = str(payload.get("updated_at") or payload.get("created_at") or "").strip()
                date = stamp[:10] if stamp else ""
                messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
                for message_index, message in enumerate(messages):
                    if not isinstance(message, dict):
                        continue
                    role = str(message.get("role") or "").lower().strip()
                    content = str(message.get("content") or "").strip()
                    if role not in {"user", "assistant"} or not content:
                        continue
                    label_bits = ["CROSS-CHAT", title]
                    if date:
                        label_bits.append(date)
                    label_bits.append(role)
                    _insert_chunks(
                        conn,
                        source_type="conversation",
                        source_key=key,
                        label=" · ".join(label_bits),
                        text=f"Conversation: {title}\n{content}",
                        mtime_ns=mtime_ns,
                        size_bytes=size_bytes,
                        message_index=message_index,
                    )
            conn.commit()
        finally:
            conn.close()
        _CHAT_SYNC_STATE.update({"db": db_key, "signature": signature, "ts": time.time()})
        return status_counts()


def remove_session(session_id: str) -> None:
    safe = "".join(ch for ch in str(session_id or "") if ch.isalnum() or ch in "-_")[:80]
    if not safe or not DB_PATH.exists():
        return
    with _LOCK:
        conn = _connect()
        try:
            _delete_source(conn, "conversation:" + safe)
            conn.commit()
        finally:
            conn.close()
        _CHAT_SYNC_STATE.update({"signature": None, "ts": 0.0})


def invalidate_sessions() -> None:
    with _LOCK:
        _CHAT_SYNC_STATE.update({"signature": None, "ts": 0.0})

def status_counts() -> dict[str, int]:
    if not DB_PATH.exists():
        return {"knowledge_chunks": 0, "conversation_chunks": 0, "total_chunks": 0}
    conn = _connect()
    try:
        knowledge = int(conn.execute("SELECT COUNT(*) FROM entries WHERE source_type='knowledge'").fetchone()[0])
        conversations = int(conn.execute("SELECT COUNT(*) FROM entries WHERE source_type='conversation'").fetchone()[0])
        total = int(conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
    finally:
        conn.close()
    return {"knowledge_chunks": knowledge, "conversation_chunks": conversations, "total_chunks": total}

def clear_index() -> None:
    with _LOCK:
        if DB_PATH.exists():
            try:
                DB_PATH.unlink()
            except OSError:
                pass
        for suffix in ("-wal", "-shm"):
            try:
                Path(str(DB_PATH) + suffix).unlink()
            except OSError:
                pass
        _SYNC_STATE.update({"db": "", "signature": None, "ts": 0.0, "counts": {"knowledge_chunks": 0, "conversation_chunks": 0, "total_chunks": 0}})
        _CHAT_SYNC_STATE.update({"db": "", "signature": None, "ts": 0.0})


def _query_rows(query: str, *, limit: int = 24) -> list[sqlite3.Row]:
    terms = _terms(query)
    if not _specific_enough(terms):
        return []
    match = " OR ".join(f'"{term}"' for term in terms)
    conn = _connect()
    try:
        return list(
            conn.execute(
                "SELECT source_type, source_key, label, ordinal, message_index, content, bm25(entries) AS rank FROM entries WHERE entries MATCH ? ORDER BY rank LIMIT ?",
                (match, max(1, min(64, int(limit)))),
            )
        )
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def build_context(session: dict[str, Any], settings: dict[str, Any], query: str) -> str:
    if not settings.get("retrieval_enabled", True):
        return ""
    terms = _terms(query)
    if not _specific_enough(terms):
        return ""

    include_knowledge = bool(settings.get("retrieval_include_knowledge", True))
    include_chat = bool(settings.get("retrieval_include_older_chat", True))
    include_cross_chat = bool(settings.get("retrieval_include_cross_chat", True))
    max_chunks = max(1, min(6, int(settings.get("retrieval_max_chunks") or 4)))
    max_chars = max(800, min(6000, int(settings.get("retrieval_max_chars") or 3600)))
    candidates: list[tuple[int, float, str, str]] = []
    required_overlap = 1 if len(terms) == 1 else 2

    # Knowledge files share the persistent FTS index with saved conversations.
    # They are synced lazily and only rewritten when a supported file's size/mtime changes.
    if include_knowledge:
        try:
            counts = sync_knowledge()
            knowledge_rows = _query_rows(query) if counts.get("knowledge_chunks") else []
            for row in knowledge_rows:
                if str(row["source_type"] or "") != "knowledge":
                    continue
                content = str(row["content"] or "").strip()
                if not content:
                    continue
                low = content.lower()
                overlap = sum(1 for term in terms if term in low)
                if overlap < required_overlap:
                    continue
                candidates.append((overlap, float(row["rank"] or 0.0), str(row["label"] or "Knowledge"), content))
        except Exception:
            # Retrieval is an enhancement. A damaged/unavailable local index
            # must never prevent the user's normal chat turn from running.
            pass

    # Saved conversations are indexed incrementally. Only changed session
    # files are rewritten, and the current conversation is excluded.
    if include_cross_chat:
        try:
            counts = sync_sessions()
            if counts.get("conversation_chunks"):
                current_key = "conversation:" + str(session.get("id") or "").strip()
                for row in _query_rows(query):
                    if str(row["source_type"] or "") != "conversation":
                        continue
                    if current_key != "conversation:" and str(row["source_key"] or "") == current_key:
                        continue
                    content = str(row["content"] or "").strip()
                    if not content:
                        continue
                    low = content.lower()
                    overlap = sum(1 for term in terms if term in low)
                    if overlap < required_overlap:
                        continue
                    candidates.append((overlap, float(row["rank"] or 0.0), str(row["label"] or "CROSS-CHAT"), content))
        except Exception:
            pass

    # Older turns are searched directly from the already-loaded session JSON.
    # This deliberately avoids rewriting a chat index on every message.
    if include_chat:
        messages = list(session.get("messages") or [])
        turn_limit = max(1, int(settings.get("history_turns") or 12)) * 2
        recent_cutoff = max(0, len(messages) - turn_limit)
        older = list(enumerate(messages[:recent_cutoff]))[-500:]
        title = str(session.get("title") or "Chat").strip() or "Chat"
        for index, message in older:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").lower()
            content = str(message.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            low = content.lower()
            overlap = sum(1 for term in terms if term in low)
            if overlap < required_overlap:
                continue
            # Negative index makes more recent older turns win ties while
            # keeping knowledge bm25 ranks meaningful enough for secondary sort.
            candidates.append((overlap, float(-index) / 100000.0, f"{title} · older {role}", content[:_CHUNK_CHARS]))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    blocks: list[str] = []
    used = 0
    seen: set[str] = set()
    for _, _, label, content in candidates:
        fingerprint = re.sub(r"\s+", " ", content.lower())[:220]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        block = f"[SOURCE: {label}]\n{content}"
        if blocks and used + len(block) + 2 > max_chars:
            continue
        if not blocks and len(block) > max_chars:
            block = block[:max_chars]
        blocks.append(block)
        used += len(block) + 2
        if len(blocks) >= max_chunks or used >= max_chars:
            break
    return "\n\n".join(blocks)

def status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    counts = status_counts()
    return {
        "enabled": bool(settings.get("retrieval_enabled", True)),
        "include_knowledge": bool(settings.get("retrieval_include_knowledge", True)),
        "include_older_chat": bool(settings.get("retrieval_include_older_chat", True)),
        "include_cross_chat": bool(settings.get("retrieval_include_cross_chat", True)),
        "knowledge_dir": str(KNOWLEDGE_DIR),
        **counts,
    }
