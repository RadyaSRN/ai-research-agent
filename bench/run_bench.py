#!/usr/bin/env python3
"""One-model benchmark runner for the `relevance_score` n8n workflow.

Iterates every item of the Langfuse dataset configured in ``_DATASET_NAME``,
dispatches each ``(idea, paper)`` pair to the ``bench_relevance_wrapper``
n8n webhook with the requested OpenRouter model, then records one trace and
one ``generation`` observation in Langfuse and links them to a dataset run.

Typical invocation:
    python3 bench/run_bench.py --model openai/gpt-5.4-nano

See ``bench/README.md`` for the full setup checklist and required n8n
workflows.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_ENV_PATH: Path = _REPO_ROOT / ".env"
_DATASET_NAME: str = "relevance_score_bench"
_WEBHOOK_PATH: str = "/webhook/bench-relevance"


def load_env(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file without any third-party dependency.

    Empty lines and comments are ignored. Values are returned verbatim; no
    quote stripping or variable interpolation is performed.

    Args:
        path: Absolute path to the ``.env`` file to load.

    Returns:
        A mapping from each declared variable name to its raw string value.
        The mapping is empty when the file does not exist.
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
class BenchConfig:
    """Immutable runtime configuration resolved from the environment.

    Attributes:
        langfuse_host: Base URL of the Langfuse instance, for example
            ``https://langfuse.example.com``. The value never carries a
            trailing slash.
        n8n_host: Base URL of the n8n instance hosting the bench wrapper.
        public_key: Langfuse public API key (``pk-lf-...``).
        secret_key: Langfuse secret API key (``sk-lf-...``).
        dataset_name: Name of the Langfuse dataset the run iterates over.
    """

    langfuse_host: str
    n8n_host: str
    public_key: str
    secret_key: str
    dataset_name: str = _DATASET_NAME

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "BenchConfig":
        """Build a :class:`BenchConfig` from a parsed env mapping.

        The process environment is consulted as a fallback when a variable is
        not present in ``env``. Bare hostnames (without a scheme) are
        promoted to ``https://``.

        Args:
            env: Mapping produced by :func:`load_env`.

        Returns:
            The resolved configuration.

        Raises:
            KeyError: If any required variable is missing both in ``env`` and
                in ``os.environ``.
        """

        def _pick(key: str) -> str:
            value = env.get(key) or os.environ.get(key)
            if not value:
                raise KeyError(f"missing required env variable: {key}")
            return value

        def _as_url(host: str) -> str:
            if host.startswith(("http://", "https://")):
                return host.rstrip("/")
            return f"https://{host.rstrip('/')}"

        return cls(
            langfuse_host=_as_url(_pick("LANGFUSE_HOST")),
            n8n_host=_as_url(_pick("N8N_HOST")),
            public_key=_pick("LANGFUSE_PUBLIC_KEY"),
            secret_key=_pick("LANGFUSE_SECRET_KEY"),
        )

    def auth_header(self) -> str:
        """Build the HTTP ``Authorization`` header for Langfuse calls.

        Returns:
            The ``Basic <token>`` value ready to drop into a request header.
        """
        raw = f"{self.public_key}:{self.secret_key}".encode()
        return f"Basic {base64.b64encode(raw).decode()}"


@dataclasses.dataclass
class ItemOutcome:
    """Progress-report shape for a single processed dataset item.

    Attributes:
        ok: Whether the upstream n8n workflow reported success.
        score: Raw ``relevance_score`` echoed back by the workflow, or the
            sentinel string ``"err"`` when the call failed.
        link_id: Identifier of the dataset-run-item record created in
            Langfuse; ``"?"`` when linking failed.
    """

    ok: bool
    score: Any
    link_id: str


def _curl(cmd: list[str]) -> str:
    """Run a ``curl`` invocation and return its stdout.

    Args:
        cmd: Fully-formed argument vector to pass to ``subprocess.run``.

    Returns:
        Standard output of the invocation (possibly empty).

    Raises:
        RuntimeError: If ``curl`` exits with a non-zero status code.
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.strip()}")
    return result.stdout


def langfuse_request(
    config: BenchConfig,
    method: str,
    path: str,
    body: Any = None,
    timeout_s: int = 30,
) -> Any:
    """Issue a JSON request against the Langfuse public API.

    Args:
        config: Resolved bench configuration.
        method: HTTP verb such as ``GET`` or ``POST``.
        path: API path starting with ``/`` (e.g. ``/api/public/ingestion``).
        body: Optional JSON-serialisable request body.
        timeout_s: Hard per-call timeout forwarded to ``curl``.

    Returns:
        The parsed JSON payload, or ``None`` when Langfuse returns an empty
        body or a non-JSON response. Non-JSON responses are logged to stderr.
    """
    cmd = [
        "curl", "-sS", "-X", method,
        f"{config.langfuse_host}{path}",
        "-H", f"Authorization: {config.auth_header()}",
        "-H", "Content-Type: application/json",
        "--max-time", str(timeout_s),
    ]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    stdout = _curl(cmd)
    if not stdout.strip():
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        print(
            f"non-JSON response from Langfuse ({path}): {stdout[:300]}",
            file=sys.stderr,
        )
        return None


def call_relevance(
    config: BenchConfig,
    idea_id: str,
    paper_id: str,
    model: str,
    trace_id: str,
    timeout_s: int = 60,
) -> dict[str, Any]:
    """Invoke the ``bench_relevance_wrapper`` n8n webhook.

    Args:
        config: Resolved bench configuration.
        idea_id: UUID of the idea stored in the ``ideas`` table.
        paper_id: Identifier of the paper, typically the ``arxiv_id`` with
            version suffix as stored in the ``papers`` table.
        model: OpenRouter model slug forwarded to the workflow.
        trace_id: 32-char hex Langfuse trace ID pre-generated by the bench.
            The n8n wrapper must echo this value into a ``langfuse_trace_id``
            field on some run-data payload so the shipper picks it up via
            ``LANGFUSE_TRACE_ID_FIELD_NAME`` and merges its OTLP spans into
            the same trace created here (see bench/README.md).
        timeout_s: Hard per-call timeout forwarded to ``curl``.

    Returns:
        Either the raw workflow output (``{"success": True, ...}``) or a
        synthetic ``{"success": False, "error": ...}`` envelope when the
        call failed or returned non-JSON content.
    """
    body = {
        "idea_id": idea_id,
        "paper_id": paper_id,
        "model": model,
        "trace_id": trace_id,
    }
    cmd = [
        "curl", "-sS", "-X", "POST",
        f"{config.n8n_host}{_WEBHOOK_PATH}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(body),
        "--max-time", str(timeout_s),
    ]
    try:
        stdout = _curl(cmd)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": f"non-JSON: {stdout[:200]}"}


def fetch_dataset_items(config: BenchConfig) -> list[dict[str, Any]]:
    """Page through every item of the target Langfuse dataset.

    Args:
        config: Resolved bench configuration.

    Returns:
        All dataset items in a single flat list, preserving server order.
    """
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        response = langfuse_request(
            config,
            "GET",
            f"/api/public/dataset-items?datasetName={config.dataset_name}"
            f"&page={page}&limit=100",
        )
        if not response:
            break
        items.extend(response.get("data") or [])
        meta = response.get("meta") or {}
        if page >= int(meta.get("totalPages", 1)):
            break
        page += 1
    return items


def ingest_events(
    config: BenchConfig,
    events: Iterable[dict[str, Any]],
) -> Any:
    """Send a batch of ingestion events to Langfuse.

    Args:
        config: Resolved bench configuration.
        events: Iterable of ingestion events shaped according to the Langfuse
            ingestion schema (``trace-create``, ``generation-create``, ...).

    Returns:
        The raw response payload from Langfuse, or ``None`` on empty replies.
    """
    return langfuse_request(
        config,
        "POST",
        "/api/public/ingestion",
        {"batch": list(events)},
    )


def link_dataset_run_item(
    config: BenchConfig,
    run_name: str,
    run_description: str,
    dataset_item_id: str,
    trace_id: str,
    observation_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    """Attach a trace/observation pair to a Langfuse dataset run.

    Args:
        config: Resolved bench configuration.
        run_name: Stable identifier of the dataset run; Langfuse creates the
            run on first use and appends items on subsequent calls.
        run_description: Human-readable description recorded on first use.
        dataset_item_id: Identifier returned by :func:`fetch_dataset_items`.
        trace_id: ID of the trace already ingested via :func:`ingest_events`.
        observation_id: ID of the generation observation under that trace.
        metadata: Free-form metadata echoed back by Langfuse.

    Returns:
        The Langfuse API response (containing the new ``id``) or ``None``
        when the request produced no parseable payload.
    """
    return langfuse_request(
        config,
        "POST",
        "/api/public/dataset-run-items",
        {
            "runName": run_name,
            "runDescription": run_description,
            "datasetItemId": dataset_item_id,
            "traceId": trace_id,
            "observationId": observation_id,
            "metadata": metadata,
        },
    )


def now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format.

    Returns:
        A timezone-aware ISO-8601 string suitable for Langfuse payloads.
    """
    return dt.datetime.now(dt.timezone.utc).isoformat()


def build_run_name(model: str, override: str | None) -> str:
    """Compose a deterministic yet unique dataset-run name.

    Args:
        model: OpenRouter model slug (``vendor/model``).
        override: Caller-supplied run name; when truthy it is returned as-is.

    Returns:
        Either ``override`` or ``<model-slug>-<YYYYMMDD>-<rand4>``.
    """
    if override:
        return override
    slug = model.split("/")[-1]
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    return f"{slug}-{today}-{uuid.uuid4().hex[:4]}"


def build_preflight_trace_event(
    *,
    item: dict[str, Any],
    model: str,
    run_name: str,
    slug: str,
    trace_id: str,
    started_at: str,
    dataset_name: str,
) -> list[dict[str, Any]]:
    """Shape the preflight ``trace-create`` event.

    Sent **before** the n8n webhook call so that Langfuse materialises the
    trace row with bench metadata (``name``, ``tags=['bench',...]``,
    ``metadata.dataset``, input) ahead of any OTLP spans that the
    ``n8n-langfuse-shipper`` might emit for the same ``trace_id`` while the
    workflow is still running. Without this preflight, the shipper's OTLP
    batch can race ahead and make the trace first appear as a plain
    production trace (``name=relevance_score``, no tags), which causes the
    production ``relevance_score_judge_experiments`` evaluator to pick it up and
    the experiment evaluator to either skip it or score against empty
    output.

    A second ``trace-create`` event follows after the webhook returns (see
    :func:`build_trace_events`) and upserts ``output`` and the final
    timestamp; Langfuse merges events that share the same trace id.
    """
    return [
        {
            "id": str(uuid.uuid4()),
            "timestamp": now_iso(),
            "type": "trace-create",
            "body": {
                "id": trace_id,
                "name": f"relevance_score_bench::{slug}",
                "timestamp": started_at,
                "input": item["input"],
                "metadata": {
                    "dataset": dataset_name,
                    "run_name": run_name,
                    "model": model,
                    "dataset_item_id": item["id"],
                    "idea_title": item["input"].get("idea_title"),
                    "rank_in_search": (item.get("metadata") or {}).get("rank_in_search"),
                },
                "tags": ["bench", "relevance_score", slug],
            },
        },
    ]


def build_trace_events(
    *,
    item: dict[str, Any],
    model: str,
    run_name: str,
    slug: str,
    trace_id: str,
    observation_id: str,
    started_at: str,
    ended_at: str,
    result: dict[str, Any],
    dataset_name: str,
) -> list[dict[str, Any]]:
    """Shape the trace + generation events for the ingestion API.

    Args:
        item: Dataset item returned by Langfuse (must contain ``input`` and
            ``id`` keys).
        model: OpenRouter slug used for this invocation.
        run_name: Dataset run name this trace will be attached to.
        slug: Short model identifier used in tags and trace names.
        trace_id: Pre-generated UUID for the trace.
        observation_id: Pre-generated UUID for the generation observation.
        started_at: ISO-8601 timestamp captured right before the webhook call.
        ended_at: ISO-8601 timestamp captured right after the webhook call.
        result: Parsed response from :func:`call_relevance`.
        dataset_name: Name of the Langfuse dataset being exercised.

    Returns:
        A two-element list ready to pass to :func:`ingest_events`: a
        ``trace-create`` event followed by a ``generation-create`` event.
    """
    ok = bool(result.get("success"))
    item_input = item["input"]
    if ok:
        # Langfuse experiment evaluators read {{output}} straight from
        # trace.output, so the judge prompt needs idea/paper ground-truth
        # fields here to avoid anchoring on the junior's own reasoning.
        # Prefer what the workflow echoed back, fall back to the dataset
        # item input which is guaranteed to carry these fields (see
        # ``bench/create_dataset.py::build_item_body``).
        output: dict[str, Any] = {
            "success": True,
            "idea_id": result.get("idea_id") or item_input.get("idea_id"),
            "paper_id": result.get("paper_id") or item_input.get("paper_id"),
            "idea_title": result.get("idea_title") or item_input.get("idea_title"),
            "idea_description": (
                result.get("idea_description") or item_input.get("idea_description")
            ),
            "paper_title": result.get("paper_title") or item_input.get("paper_title"),
            "paper_abstract": (
                result.get("paper_abstract") or item_input.get("paper_abstract")
            ),
            "relevance_score": result.get("relevance_score"),
            "reasoning": result.get("reasoning"),
            "key_concepts_matched": result.get("key_concepts_matched"),
        }
    else:
        output = {"error": result.get("error", "unknown")}

    trace_name = f"relevance_score_bench::{slug}"
    return [
        {
            "id": str(uuid.uuid4()),
            "timestamp": now_iso(),
            "type": "trace-create",
            "body": {
                "id": trace_id,
                "name": trace_name,
                "timestamp": started_at,
                "input": item["input"],
                "output": output,
                "metadata": {
                    "dataset": dataset_name,
                    "run_name": run_name,
                    "model": model,
                    "dataset_item_id": item["id"],
                    "idea_title": item["input"].get("idea_title"),
                    "rank_in_search": (item.get("metadata") or {}).get("rank_in_search"),
                },
                "tags": ["bench", "relevance_score", slug],
            },
        },
        {
            "id": str(uuid.uuid4()),
            "timestamp": now_iso(),
            "type": "generation-create",
            "body": {
                "id": observation_id,
                "traceId": trace_id,
                "name": "relevance_score_llm",
                "startTime": started_at,
                "endTime": ended_at,
                "model": model,
                "input": item["input"],
                "output": output,
                "level": "DEFAULT" if ok else "ERROR",
            },
        },
    ]


def run_single_item(
    config: BenchConfig,
    item: dict[str, Any],
    model: str,
    slug: str,
    run_name: str,
) -> ItemOutcome:
    """Execute the full bench loop body for a single dataset item.

    Runs the n8n webhook, ingests the trace + generation, and links the
    trace to the dataset run in Langfuse.

    Args:
        config: Resolved bench configuration.
        item: Dataset item as returned by :func:`fetch_dataset_items`.
        model: OpenRouter slug to benchmark.
        slug: Short model identifier derived from ``model``.
        run_name: Stable name of the dataset run aggregating this call.

    Returns:
        A lightweight :class:`ItemOutcome` consumed by the progress logger.
    """
    # Hex (no dashes) so the n8n-langfuse-shipper accepts the value when it
    # parses ``langfuse_trace_id`` out of the workflow run-data via the
    # ``LANGFUSE_TRACE_ID_FIELD_NAME`` regex; Langfuse OTLP ingestion only
    # merges spans whose trace_id is a valid 32-char hex string.
    trace_id = uuid.uuid4().hex
    observation_id = uuid.uuid4().hex
    started_at = now_iso()
    # Preflight ingest: register the trace in Langfuse with bench ``name`` +
    # ``tags`` before the n8n execution starts, so OTLP spans emitted by the
    # shipper can only land on an already-bench-labelled trace and never
    # race us into looking like a production ``relevance_score`` trace.
    ingest_events(
        config,
        build_preflight_trace_event(
            item=item,
            model=model,
            run_name=run_name,
            slug=slug,
            trace_id=trace_id,
            started_at=started_at,
            dataset_name=config.dataset_name,
        ),
    )
    result = call_relevance(
        config,
        idea_id=item["input"]["idea_id"],
        paper_id=item["input"]["paper_id"],
        model=model,
        trace_id=trace_id,
    )
    ended_at = now_iso()
    events = build_trace_events(
        item=item,
        model=model,
        run_name=run_name,
        slug=slug,
        trace_id=trace_id,
        observation_id=observation_id,
        started_at=started_at,
        ended_at=ended_at,
        result=result,
        dataset_name=config.dataset_name,
    )
    ingest_events(config, events)
    link = link_dataset_run_item(
        config,
        run_name=run_name,
        run_description=f"Bench run for relevance_score with model {model}",
        dataset_item_id=item["id"],
        trace_id=trace_id,
        observation_id=observation_id,
        metadata={"model": model},
    )
    return ItemOutcome(
        ok=bool(result.get("success")),
        score=result.get("relevance_score", "err"),
        link_id=(link or {}).get("id", "?"),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Define and parse CLI arguments for ``run_bench.py``.

    Args:
        argv: Optional explicit argument vector; ``None`` falls back to
            ``sys.argv[1:]``.

    Returns:
        The populated :class:`argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        required=True,
        help="OpenRouter model slug, e.g. 'openai/gpt-5.4-nano'.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Override the auto-generated dataset run name.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N dataset items (0 = all).",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Entry point for CLI invocation.

    Returns:
        ``0`` when all dataset items were processed without a fatal error,
        ``1`` on configuration issues.
    """
    args = parse_args()
    try:
        config = BenchConfig.from_env(load_env(_ENV_PATH))
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    slug = args.model.split("/")[-1]
    run_name = build_run_name(args.model, args.run_name)

    print("== Bench run ==")
    print(f"  model    : {args.model}")
    print(f"  dataset  : {config.dataset_name}")
    print(f"  run_name : {run_name}")

    items = fetch_dataset_items(config)
    print(f"  items    : {len(items)}")
    if args.limit:
        items = items[: args.limit]
        print(f"  limited to: {len(items)}")

    t0 = time.time()
    ok = 0
    fail = 0
    for idx, item in enumerate(items, 1):
        outcome = run_single_item(config, item, args.model, slug, run_name)
        if outcome.ok:
            ok += 1
        else:
            fail += 1
        print(
            f"  {idx:2d}/{len(items)}  item={item['id'][:8]}  "
            f"{slug:>20s}  score={outcome.score}  link_id={outcome.link_id[:8]}"
        )

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. ok={ok} fail={fail}")
    print(
        f"View in Langfuse: {config.langfuse_host}/datasets/{config.dataset_name} "
        f"(filter runs by '{run_name}')"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
