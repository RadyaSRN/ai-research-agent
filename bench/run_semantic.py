#!/usr/bin/env python3
"""Verification utility that re-runs semantic search for each bench idea.

For each of the four hard-coded research ideas the script calls the
``bench_search_helper`` n8n webhook (a thin wrapper around the
``semantic_search_papers`` workflow), fetches the top-K results, and prints
which of the originally curated targets are still in the top-5.

This is an *optional* tool used only when curating the bench dataset. After
the dataset has been uploaded to Langfuse there is no need to run it
routinely; keep it for reproducibility.

Typical invocation:
    python3 bench/run_semantic.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_ENV_PATH: Path = _REPO_ROOT / ".env"
_OUT_PATH: Path = Path(__file__).resolve().parent / "semantic_results.json"
_WEBHOOK_PATH: str = "/webhook/bench-search"

IDEAS: dict[str, dict[str, Any]] = {
    "f0e2cc18-9245-4318-b777-45ced0e3105c": {
        "title": "Entropy-weighted token-level advantage in GRPO",
        "query": (
            "Entropy-weighted token-level advantage in GRPO. token-level "
            "advantage, per-token entropy, GRPO variance reduction, "
            "surprisal weighting, decision tokens. Standard GRPO uses "
            "trajectory-level advantage for all tokens; weight gradient by "
            "per-token entropy/surprisal to emphasize decision tokens and "
            "dampen trivial ones."
        ),
        "targets": [
            "2603.28204",
            "2604.11056",
            "2602.03309",
            "2510.06870",
            "2604.02795",
        ],
    },
    "97638342-6a91-4949-8476-fa080981ecee": {
        "title": "Adaptive group size in GRPO by prompt difficulty",
        "query": (
            "Adaptive group size in GRPO by prompt difficulty. GRPO, "
            "adaptive group size, variance reduction, curriculum, rollout "
            "budget. Adaptively choose group size G per prompt difficulty; "
            "fewer rollouts for easy prompts, more for hard, to reduce "
            "compute or improve quality."
        ),
        "targets": [
            "2602.14338",
            "2602.01601",
            "2512.02882",
            "2603.01106",
            "2603.21177",
        ],
    },
    "72a1d61d-690c-461a-9cdb-88575eda1b8a": {
        "title": "CFG in latent activation space",
        "query": (
            "CFG in latent activation space. classifier-free guidance, "
            "activation space, diffusion, controllability, internal "
            "representations. Apply classifier-free guidance directly in "
            "internal activation space of neural network rather than only "
            "in output or noise space."
        ),
        "targets": [
            "2604.09213",
            "2603.17825",
            "2410.23054",
            "2512.03661",
            "2412.09646",
        ],
    },
    "5758e186-8ef8-4226-9f09-a96b69893494": {
        "title": "Alternative control surfaces in CFG-ctrl",
        "query": (
            "Alternative control surfaces in CFG-ctrl. diffusion, CFG-ctrl, "
            "control surface, reaching law, guidance. Compare alternative "
            "control surfaces and reaching laws in CFG-ctrl; their effect "
            "on stability, convergence speed, and sampling quality in "
            "diffusion models."
        ),
        "targets": [
            "2603.03281",
            "2603.11509",
            "2509.22007",
            "2404.13040",
            "2603.25734",
        ],
    },
}


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


def resolve_n8n_base(env: dict[str, str]) -> str:
    """Resolve the n8n base URL from environment variables.

    Args:
        env: Mapping produced by :func:`load_env`.

    Returns:
        An absolute URL without trailing slash.

    Raises:
        KeyError: If ``N8N_HOST`` is missing in both ``env`` and
            ``os.environ``.
    """
    host = env.get("N8N_HOST") or os.environ.get("N8N_HOST")
    if not host:
        raise KeyError("N8N_HOST")
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host.rstrip("/")


def strip_version(arxiv_id: str) -> str:
    """Drop the trailing version suffix from an arXiv identifier.

    Args:
        arxiv_id: Full arXiv id such as ``2603.28204v2``.

    Returns:
        The identifier without any trailing ``vN``; empty input yields
        empty output.
    """
    return re.sub(r"v\d+$", "", arxiv_id or "")


def run_search(base_url: str, query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Call the ``bench_search_helper`` webhook and parse the response.

    Args:
        base_url: Absolute n8n base URL produced by :func:`resolve_n8n_base`.
        query: Natural-language query forwarded to the semantic search
            workflow.
        top_k: Number of nearest neighbours to request from the workflow.

    Returns:
        The ``results`` array returned by the workflow, or an empty list
        when the call failed or returned non-JSON content.
    """
    payload = json.dumps({"query": query, "top_k": top_k})
    cmd = [
        "curl", "-sS", "-X", "POST",
        f"{base_url}{_WEBHOOK_PATH}",
        "-H", "Content-Type: application/json",
        "-d", payload,
        "--max-time", "60",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERR: {result.stderr.strip()}", file=sys.stderr)
        return []
    try:
        data: Any = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"ERR parsing: {result.stdout[:200]}", file=sys.stderr)
        return []
    if isinstance(data, list):
        data = data[0] if data else {}
    return data.get("results", []) or []


def report_idea(
    title: str,
    targets: Iterable[str],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Print a comparison report for a single idea and return a summary.

    Args:
        title: Human-readable idea title used as a section header.
        targets: arXiv ids (without version suffix) that were originally
            curated as "expected" top-5.
        results: Return value of :func:`run_search` for that idea.

    Returns:
        A dictionary with the idea title, the expected targets, and the
        top-10 arXiv ids actually returned by the search.
    """
    target_set = set(targets)
    top_ids = [strip_version(r.get("arxiv_id", "")) for r in results]
    print(f"  top-10 semantic search output:")
    for i, row in enumerate(results):
        base = strip_version(row.get("arxiv_id", ""))
        hit_marker = "*" if base in target_set else " "
        dist = row.get("distance", float("nan"))
        head = (row.get("title") or "")[:80]
        dist_str = f"{dist:.4f}" if isinstance(dist, (int, float)) else str(dist)
        print(f"  {hit_marker} {i}. {row.get('arxiv_id', '')}  dist={dist_str}  {head}")
    hits_in_top5 = sum(1 for aid in top_ids[:5] if aid in target_set)
    missing = target_set - set(top_ids[:5])
    print(f"  Of {len(target_set)} targets, hits in top-5: {hits_in_top5} / 5")
    print(f"  Missing from top-5: {missing}")
    return {"title": title, "targets": list(target_set), "top10": top_ids}


def main() -> int:
    """Entry point for CLI invocation.

    Runs a semantic search for every entry in :data:`IDEAS` and writes a
    summary JSON next to this script.

    Returns:
        ``0`` on success, ``1`` on a configuration error.
    """
    try:
        base_url = resolve_n8n_base(load_env(_ENV_PATH))
    except KeyError as exc:
        print(f"ERROR: missing env variable {exc}", file=sys.stderr)
        return 1

    all_results: dict[str, Any] = {}
    for idea_id, meta in IDEAS.items():
        print(f"\n=== {meta['title']}")
        results = run_search(base_url, meta["query"], top_k=10)
        all_results[idea_id] = report_idea(meta["title"], meta["targets"], results)

    _OUT_PATH.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"\nWrote {_OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
