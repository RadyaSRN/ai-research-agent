#!/usr/bin/env python3
"""Синхронизация prompts/*.md с Langfuse Prompt Management.

Подкоманды:

* ``pull``   — Langfuse → prompts/ (инициализация / backup).
* ``push``   — prompts/ → Langfuse. Создаёт новую версию и ставит label
              ``production`` только если тело или config действительно
              изменились (по хешу).
* ``check``  — проверка: exit 1, если локальные файлы разъехались с
              production-версией в Langfuse. Ничего не меняет. Для CI.

Каждый файл `prompts/<name>.md` состоит из YAML-frontmatter и тела:

    ---
    name: relevance_score
    type: text               # text | chat
    labels: [production]
    tags: [...]
    config:
      model: google/gemini-3-flash-preview
      temperature: 0.0
    ---

    <prompt body>            # для type=text

Для ``type: chat`` вместо тела используется поле ``messages`` в frontmatter
(список объектов ``{role, content}``), тело markdown оставляется пустым.

Имя файла без ``.md`` обязано совпадать с ``name`` в frontmatter.

Использует ``.env`` в корне репо для ``LANGFUSE_HOST`` / ``LANGFUSE_PUBLIC_KEY``
/ ``LANGFUSE_SECRET_KEY``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import frontmatter  # python-frontmatter
    from langfuse import Langfuse
except ImportError as e:  # pragma: no cover
    sys.stderr.write(
        f"error: отсутствует зависимость ({e.name}). Установи: "
        f"pip install -r scripts/requirements.txt\n"
    )
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
ENV_FILE = REPO_ROOT / ".env"


# ──────────────────────────── bootstrap ────────────────────────────

def _load_env(path: Path) -> None:
    """Минимальный .env-парсер в os.environ (shell-style KEY=VALUE)."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _make_client() -> Langfuse:
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"
    if host and not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    if not pk or not sk:
        sys.stderr.write(
            "error: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY не заданы в .env\n"
        )
        sys.exit(2)
    return Langfuse(public_key=pk, secret_key=sk, host=host)


# ──────────────────────────── normalization ────────────────────────────

def _canonical_config(cfg: Any) -> str:
    """Стабильная сериализация config для сравнения (JSON + sorted keys)."""
    return json.dumps(cfg or {}, sort_keys=True, ensure_ascii=False)


def _canonical_body(body_or_messages: Any, prompt_type: str) -> str:
    """Тело для сравнения. Для text — нормализованная строка, для chat —
    канонический JSON массива сообщений."""
    if prompt_type == "chat":
        return json.dumps(body_or_messages or [], sort_keys=True, ensure_ascii=False)
    return (body_or_messages or "").strip()


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


# ──────────────────────────── local files ────────────────────────────

class LocalPrompt:
    __slots__ = ("path", "name", "type", "labels", "tags", "config", "body", "messages")

    def __init__(self, path: Path):
        post = frontmatter.load(path)
        meta = post.metadata or {}
        file_stem = path.stem
        self.path = path
        self.name = str(meta.get("name") or file_stem)
        self.type = str(meta.get("type") or "text")
        self.labels = list(meta.get("labels") or [])
        self.tags = list(meta.get("tags") or [])
        self.config = meta.get("config") or {}
        if self.type == "chat":
            self.messages = list(meta.get("messages") or [])
            self.body = ""
        else:
            self.messages = []
            self.body = post.content
        if self.name != file_stem:
            sys.stderr.write(
                f"error: {path.name}: frontmatter.name='{self.name}' не совпадает "
                f"с именем файла '{file_stem}'\n"
            )
            sys.exit(2)
        if self.type not in ("text", "chat"):
            sys.stderr.write(f"error: {path.name}: unsupported type='{self.type}'\n")
            sys.exit(2)

    @property
    def payload(self) -> Any:
        return self.messages if self.type == "chat" else self.body

    def hash(self) -> str:
        return _hash(
            self.type,
            _canonical_body(self.payload, self.type),
            _canonical_config(self.config),
        )


def _load_locals() -> list[LocalPrompt]:
    if not PROMPTS_DIR.is_dir():
        sys.stderr.write(f"error: {PROMPTS_DIR} не существует\n")
        sys.exit(2)
    files = sorted(p for p in PROMPTS_DIR.glob("*.md") if p.name != "README.md")
    return [LocalPrompt(p) for p in files]


# ──────────────────────────── Langfuse adapter ────────────────────────────

def _remote_hash(remote: Any) -> str:
    """Хеш для Langfuse-объекта промпта (TextPromptClient / ChatPromptClient)."""
    prompt_type = "chat" if isinstance(remote.prompt, list) else "text"
    return _hash(
        prompt_type,
        _canonical_body(remote.prompt, prompt_type),
        _canonical_config(remote.config),
    )


def _fetch_remote(lf: Langfuse, name: str):
    try:
        return lf.get_prompt(name=name, label="production", cache_ttl_seconds=0)
    except Exception as e:  # noqa: BLE001 — SDK кидает разные типы
        msg = str(e).lower()
        if "not found" in msg or "404" in msg:
            return None
        raise


# ──────────────────────────── pull / push / check ────────────────────────────

def _dump_local(lp: LocalPrompt, remote: Any) -> None:
    """Переписать локальный файл содержимым remote."""
    remote_type = "chat" if isinstance(remote.prompt, list) else "text"
    meta = {
        "name": lp.name,
        "type": remote_type,
        "labels": sorted(set(list(remote.labels or []) + ["production"])),
    }
    if remote.tags:
        meta["tags"] = list(remote.tags)
    if remote.config:
        meta["config"] = remote.config
    if remote_type == "chat":
        meta["messages"] = remote.prompt
        body = ""
    else:
        body = (remote.prompt or "").rstrip() + "\n"
    post = frontmatter.Post(body, **meta)
    lp.path.write_text(frontmatter.dumps(post) + "\n")


def cmd_pull(lf: Langfuse, locals_: list[LocalPrompt]) -> int:
    changed = 0
    for lp in locals_:
        remote = _fetch_remote(lf, lp.name)
        if remote is None:
            print(f"[pull] {lp.name}: нет в Langfuse (skip)")
            continue
        if _remote_hash(remote) == lp.hash():
            print(f"[pull] {lp.name}: up-to-date")
            continue
        _dump_local(lp, remote)
        print(f"[pull] {lp.name}: UPDATED (v{remote.version})")
        changed += 1
    print(f"[pull] done. {changed} file(s) updated.")
    return 0


def cmd_push(lf: Langfuse, locals_: list[LocalPrompt]) -> int:
    pushed = 0
    for lp in locals_:
        remote = _fetch_remote(lf, lp.name)
        if remote is not None and _remote_hash(remote) == lp.hash():
            print(f"[push] {lp.name}: unchanged (remote v{remote.version})")
            continue
        labels = sorted(set(lp.labels or ["production"]))
        print(f"[push] {lp.name}: creating new version (labels={labels})")
        if lp.type == "chat":
            lf.create_prompt(
                name=lp.name,
                type="chat",
                prompt=lp.messages,
                labels=labels,
                tags=lp.tags or None,
                config=lp.config or None,
            )
        else:
            lf.create_prompt(
                name=lp.name,
                type="text",
                prompt=lp.body.strip(),
                labels=labels,
                tags=lp.tags or None,
                config=lp.config or None,
            )
        pushed += 1
    print(f"[push] done. {pushed} version(s) created.")
    return 0


def cmd_check(lf: Langfuse, locals_: list[LocalPrompt]) -> int:
    diverged: list[str] = []
    for lp in locals_:
        remote = _fetch_remote(lf, lp.name)
        if remote is None:
            diverged.append(f"{lp.name}: отсутствует в Langfuse")
            continue
        if _remote_hash(remote) != lp.hash():
            diverged.append(f"{lp.name}: разъехался с Langfuse v{remote.version}")
    if diverged:
        print("[check] FAIL:")
        for d in diverged:
            print(f"  - {d}")
        return 1
    print(f"[check] OK: {len(locals_)} prompt(s) in sync.")
    return 0


# ──────────────────────────── CLI ────────────────────────────

def main() -> int:
    _load_env(ENV_FILE)

    parser = argparse.ArgumentParser(
        description="Синхронизация prompts/*.md с Langfuse Prompt Management",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull", help="Langfuse → prompts/")
    sub.add_parser("push", help="prompts/ → Langfuse (label=production)")
    sub.add_parser("check", help="exit 1 если prompts/ разъехался с Langfuse")
    args = parser.parse_args()

    lf = _make_client()
    locals_ = _load_locals()
    if not locals_:
        print("error: в prompts/ нет ни одного .md (кроме README.md)", file=sys.stderr)
        return 2

    if args.cmd == "pull":
        return cmd_pull(lf, locals_)
    if args.cmd == "push":
        return cmd_push(lf, locals_)
    if args.cmd == "check":
        return cmd_check(lf, locals_)
    return 2


if __name__ == "__main__":
    sys.exit(main())
