#!/usr/bin/env python3
"""One-shot setup for the Langfuse dataset ``relevance_score_bench``.

Reads ``bench/final_20_pairs.json`` (the curated (idea, paper) pairs),
enriches each pair with live title/description/abstract data pulled straight
from the project Postgres, and uploads the 20 items to Langfuse via the
public API.

Safe to re-run: creating the dataset is idempotent (existing datasets are
ignored), and item inserts are retried-free but collision-free on the
Langfuse side because Langfuse generates its own IDs.

Typical invocation:
    python3 bench/create_dataset.py

See ``bench/README.md`` for prerequisites.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_ENV_PATH: Path = _REPO_ROOT / ".env"
_PAIRS_PATH: Path = Path(__file__).resolve().parent / "final_20_pairs.json"
_COMPOSE_PATH: Path = _REPO_ROOT / "docker-compose.yml"

_DATASET_NAME: str = "relevance_score_bench"
_DATASET_DESCRIPTION: str = (
    "Benchmark dataset for relevance_score workflow — "
    "4 ideas x 5 papers (actual semantic_search top-5)."
)


def load_env(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file without any third-party dependency.

    Empty lines and comments are ignored; values are returned verbatim.

    Args:
        path: Absolute path to the ``.env`` file to load.

    Returns:
        Mapping from variable name to raw value; empty if the file is absent.
    """
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


@dataclasses.dataclass(frozen=True)
class LangfuseAuth:
    """Langfuse API credentials pulled from the environment.

    Attributes:
        host: Base URL of the Langfuse instance, without trailing slash.
        public_key: Langfuse public API key (``pk-lf-...``).
        secret_key: Langfuse secret API key (``sk-lf-...``).
    """

    host: str
    public_key: str
    secret_key: str

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "LangfuseAuth":
        """Build credentials from a parsed env mapping.

        Args:
            env: Mapping produced by :func:`load_env`.

        Returns:
            The resolved credentials.

        Raises:
            KeyError: If any required variable is missing both in ``env`` and
                in ``os.environ``.
        """

        def _pick(key: str) -> str:
            value = env.get(key) or os.environ.get(key)
            if not value:
                raise KeyError(f"missing required env variable: {key}")
            return value

        host = _pick("LANGFUSE_HOST")
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return cls(
            host=host.rstrip("/"),
            public_key=_pick("LANGFUSE_PUBLIC_KEY"),
            secret_key=_pick("LANGFUSE_SECRET_KEY"),
        )

    def header(self) -> str:
        """Build the ``Basic <token>`` HTTP authorization header.

        Returns:
            A ready-to-use ``Authorization`` header value.
        """
        raw = f"{self.public_key}:{self.secret_key}".encode()
        return f"Basic {base64.b64encode(raw).decode()}"


def langfuse_request(
    auth: LangfuseAuth,
    method: str,
    path: str,
    body: Any = None,
) -> Any:
    """Execute a JSON request against the Langfuse public API.

    Args:
        auth: Credentials and host resolved from the environment.
        method: HTTP verb such as ``GET`` or ``POST``.
        path: API path starting with ``/``.
        body: Optional JSON-serialisable request body.

    Returns:
        The parsed JSON payload, or ``None`` if the response body is empty.

    Raises:
        RuntimeError: If ``curl`` fails.
        json.JSONDecodeError: If the response body is non-empty and cannot
            be parsed as JSON.
    """
    cmd = [
        "curl", "-sS", "-X", method,
        f"{auth.host}{path}",
        "-H", f"Authorization: {auth.header()}",
        "-H", "Content-Type: application/json",
    ]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.strip()}")
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"RAW response: {result.stdout[:500]}", file=sys.stderr)
        raise


def fetch_idea_and_paper(idea_id: str, arxiv_id: str) -> dict[str, Any]:
    """Pull idea and paper details from Postgres via ``docker compose exec``.

    Args:
        idea_id: UUID of the idea.
        arxiv_id: arXiv identifier as stored in the ``papers`` table,
            including the trailing version suffix (for example
            ``2603.28204v2``).

    Returns:
        A flat dictionary with the joined idea and paper columns.

    Raises:
        RuntimeError: If ``psql`` fails or no matching row is found.
    """
    query = (
        "SELECT json_build_object("
        "'idea_id', i.id::text,"
        "'idea_title', i.title,"
        "'idea_description', i.description,"
        "'idea_keywords', i.keywords,"
        "'paper_id', p.id::text,"
        "'paper_arxiv_id', p.arxiv_id,"
        "'paper_title', p.title,"
        "'paper_abstract', p.abstract"
        ") AS data "
        "FROM ideas i "
        f"JOIN papers p ON p.arxiv_id = '{arxiv_id}' "
        f"WHERE i.id = '{idea_id}' LIMIT 1;"
    )
    cmd = [
        "docker", "compose", "-f", str(_COMPOSE_PATH),
        "exec", "-T", "postgres",
        "psql", "-U", "postgres", "-d", "app",
        "-t", "-A", "-c", query,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip()}")
    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError(
            f"no row for idea={idea_id} arxiv={arxiv_id} — "
            "did you run the ingestion step first?"
        )
    return json.loads(raw)


def load_pairs(path: Path) -> list[dict[str, Any]]:
    """Load the curated ``(idea, paper)`` pairs from disk.

    Args:
        path: Path to ``final_20_pairs.json``.

    Returns:
        The ``pairs`` array from the JSON document.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        KeyError: If the JSON document lacks a ``pairs`` key.
    """
    payload = json.loads(path.read_text())
    return payload["pairs"]


def ensure_dataset(auth: LangfuseAuth, name: str, description: str) -> None:
    """Create the Langfuse dataset when it does not yet exist.

    Langfuse returns an error on duplicate names, which is caught and logged
    so the caller can proceed to upload items into the pre-existing dataset.

    Args:
        auth: Resolved Langfuse credentials.
        name: Desired dataset name.
        description: Long-form description stored on the dataset.
    """
    print(f"Creating dataset {name}...")
    try:
        response = langfuse_request(
            auth,
            "POST",
            "/api/public/v2/datasets",
            {
                "name": name,
                "description": description,
                "metadata": {
                    "created_by": "bench_setup",
                    "items": 20,
                    "ideas": 4,
                    "ppi": 5,
                },
            },
        )
        new_id = (response or {}).get("id", "no id")
        print(f"  created: {new_id}")
    except Exception as exc:
        print(f"  dataset probably already exists, continuing: {exc}")


def build_item_body(
    pair: dict[str, Any],
    joined: dict[str, Any],
    dataset_name: str,
) -> dict[str, Any]:
    """Build the payload uploaded for one dataset item.

    Args:
        pair: Entry from ``final_20_pairs.json`` (contains ``idea_id``,
            ``arxiv_id``, ``rank`` and a display ``idea_title``).
        joined: Row returned by :func:`fetch_idea_and_paper`.
        dataset_name: Target Langfuse dataset name.

    Returns:
        A dictionary shaped for ``POST /api/public/dataset-items``.
    """
    return {
        "datasetName": dataset_name,
        "input": {
            "idea_id": joined["idea_id"],
            # `relevance_score` workflow accepts the arxiv_id (with version
            # suffix) as the paper identifier.
            "paper_id": pair["arxiv_id"],
            "idea_title": joined["idea_title"],
            "idea_description": joined["idea_description"],
            "idea_keywords": joined["idea_keywords"],
            "paper_title": joined["paper_title"],
            "paper_abstract": joined["paper_abstract"],
        },
        "metadata": {
            "idea_title": pair["idea_title"],
            "rank_in_search": pair["rank"],
        },
    }


def upload_items(
    auth: LangfuseAuth,
    pairs: list[dict[str, Any]],
    dataset_name: str,
) -> None:
    """Upload every curated pair as a Langfuse dataset item.

    Args:
        auth: Resolved Langfuse credentials.
        pairs: Output of :func:`load_pairs`.
        dataset_name: Target dataset name (must already exist in Langfuse).
    """
    total = len(pairs)
    for idx, pair in enumerate(pairs, 1):
        joined = fetch_idea_and_paper(pair["idea_id"], pair["arxiv_id"])
        body = build_item_body(pair, joined, dataset_name)
        response = langfuse_request(auth, "POST", "/api/public/dataset-items", body)
        item_id = (response or {}).get("id", "?")
        print(
            f"  {idx:2d}/{total}  idea='{pair['idea_title'][:50]}'  "
            f"arxiv={pair['arxiv_id']}  -> id={item_id}"
        )


def main() -> int:
    """Entry point for CLI invocation.

    Returns:
        ``0`` on successful run, ``1`` on a configuration error.
    """
    try:
        auth = LangfuseAuth.from_env(load_env(_ENV_PATH))
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    pairs = load_pairs(_PAIRS_PATH)
    ensure_dataset(auth, _DATASET_NAME, _DATASET_DESCRIPTION)
    upload_items(auth, pairs, _DATASET_NAME)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
