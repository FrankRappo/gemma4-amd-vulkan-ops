#!/usr/bin/env python3
"""Measure prompt processing and token generation through llama-server.

The prompts are deterministic and deliberately start with a different marker for
each sample.  This prevents a previous slot prefix from turning later samples
into prompt-cache benchmarks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
import urllib.request
from pathlib import Path
from typing import Any


PROMPT_UNIT = (
    "Проверка ускорения Vulkan. Модель должна обработать длинный контекст "
    "без изменения результата и затем продолжить последовательность. "
)


def request_json(
    base_url: str, path: str, payload: dict[str, Any] | None, timeout: int
) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def tokenize(base_url: str, text: str, timeout: int) -> int:
    response = request_json(base_url, "/tokenize", {"content": text}, timeout)
    return len(response["tokens"])


def active_slot_count(slots: Any) -> int:
    """Return the number of llama-server slots currently doing work."""
    if not isinstance(slots, list):
        raise ValueError(f"unexpected /slots response: {slots!r}")
    active = 0
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError(f"unexpected slot record: {slot!r}")
        if slot.get("is_processing", False):
            active += 1
    return active


def wait_for_idle_window(
    base_url: str,
    idle_window: float,
    idle_timeout: float,
    poll_interval: float,
    request_timeout: int,
) -> None:
    """Require all server slots to remain idle for a continuous interval.

    A failed or blocked /slots request resets the interval.  This deliberately
    prefers refusing a benchmark over silently recording a sample contaminated
    by a production request.
    """
    if idle_window <= 0:
        return
    deadline = time.monotonic() + idle_timeout
    idle_since: float | None = None
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            slots = request_json(base_url, "/slots", None, request_timeout)
            if active_slot_count(slots) == 0:
                now = time.monotonic()
                if idle_since is None:
                    idle_since = now
                elif now - idle_since >= idle_window:
                    # Close the polling race immediately before admitting the
                    # benchmark sample.
                    slots = request_json(base_url, "/slots", None, request_timeout)
                    if active_slot_count(slots) == 0:
                        return
                    idle_since = None
            else:
                idle_since = None
            last_error = None
        except Exception as error:  # network/JSON errors all invalidate idleness
            last_error = error
            idle_since = None
        time.sleep(poll_interval)
    detail = f": last /slots error: {last_error}" if last_error else ""
    raise TimeoutError(
        f"llama-server did not remain fully idle for {idle_window:g}s "
        f"within {idle_timeout:g}s{detail}"
    )


def make_prompt(base_url: str, sample: int, target_tokens: int, timeout: int) -> tuple[str, int]:
    marker = f"SAMPLE-{sample:04d}-NO-CACHE\n"
    low, high = 1, max(target_tokens, 2)
    while tokenize(base_url, marker + PROMPT_UNIT * high, timeout) < target_tokens:
        high *= 2
    while low < high:
        middle = (low + high) // 2
        count = tokenize(base_url, marker + PROMPT_UNIT * middle, timeout)
        if count < target_tokens:
            low = middle + 1
        else:
            high = middle
    candidates = [max(1, low - 1), low]
    prompt, count = min(
        (
            (marker + PROMPT_UNIT * repeats, tokenize(base_url, marker + PROMPT_UNIT * repeats, timeout))
            for repeats in candidates
        ),
        key=lambda item: abs(item[1] - target_tokens),
    )
    return prompt, count


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    prompt_rates = [record["prompt_per_second"] for record in records]
    generation_rates = [record["predicted_per_second"] for record in records]
    return {
        "samples": len(records),
        "median_prompt_tps": statistics.median(prompt_rates),
        "mean_prompt_tps": statistics.fmean(prompt_rates),
        "median_generation_tps": statistics.median(generation_rates),
        "mean_generation_tps": statistics.fmean(generation_rates),
        "total_wall_seconds": sum(record["wall_seconds"] for record in records),
    }


def forced_output_grammar(generation_tokens: int) -> str:
    # A long single-path grammar keeps the generated bytes identical across
    # numerically different but correct GPU kernels.  The model still performs
    # every decode step, so generation timing remains comparable.
    literal = " 0" * max(256, generation_tokens * 2)
    return "root ::= " + json.dumps(literal)


def run(args: argparse.Namespace) -> None:
    health = request_json(args.base_url, "/health", None, args.timeout)
    if health.get("status") != "ok":
        raise SystemExit(f"llama-server is not healthy: {health!r}")

    records = []
    for sample in range(1, args.samples + 1):
        wait_for_idle_window(
            args.base_url,
            args.idle_window,
            args.idle_timeout,
            args.idle_poll_interval,
            min(args.timeout, args.idle_request_timeout),
        )
        prompt, prompt_tokens_requested = make_prompt(
            args.base_url, sample, args.prompt_tokens, args.timeout
        )
        payload = {
            "prompt": prompt,
            "n_predict": args.generation_tokens,
            "temperature": 0,
            "top_k": 1,
            "seed": 42,
            "cache_prompt": False,
            "stream": False,
            "grammar": forced_output_grammar(args.generation_tokens),
        }
        started = time.monotonic()
        response = request_json(args.base_url, "/completion", payload, args.timeout)
        wall_seconds = time.monotonic() - started
        timings = response["timings"]
        content = response.get("content", "")
        record = {
            "sample": sample,
            "requested_prompt_tokens": prompt_tokens_requested,
            "prompt_tokens": timings["prompt_n"],
            "prompt_ms": timings["prompt_ms"],
            "prompt_per_second": timings["prompt_per_second"],
            "predicted_tokens": timings["predicted_n"],
            "predicted_ms": timings["predicted_ms"],
            "predicted_per_second": timings["predicted_per_second"],
            "wall_seconds": wall_seconds,
            "output_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "output": content,
        }
        records.append(record)
        print(
            f"sample={sample} prompt={record['prompt_tokens']} "
            f"pp={record['prompt_per_second']:.3f} tok/s "
            f"tg={record['predicted_per_second']:.3f} tok/s "
            f"wall={wall_seconds:.3f}s",
            flush=True,
        )

    artifact = {
        "label": args.label,
        "base_url": args.base_url,
        "configuration": {
            "target_prompt_tokens": args.prompt_tokens,
            "generation_tokens": args.generation_tokens,
            "samples": args.samples,
            "temperature": 0,
            "top_k": 1,
            "seed": 42,
            "cache_prompt": False,
            "forced_single_path_grammar": True,
            "idle_window_seconds": args.idle_window,
        },
        "summary": summarize(records),
        "results": records,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False), flush=True)


def comparison_report(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    minimum_prefill_speedup: float,
    maximum_generation_regression: float,
) -> dict[str, Any]:
    baseline_results = {item["sample"]: item for item in baseline["results"]}
    candidate_results = {item["sample"]: item for item in candidate["results"]}
    if baseline_results.keys() != candidate_results.keys():
        raise ValueError("baseline and candidate sample sets differ")
    mismatches = [
        sample
        for sample in baseline_results
        if baseline_results[sample]["output_sha256"]
        != candidate_results[sample]["output_sha256"]
    ]
    baseline_prompt = baseline["summary"]["median_prompt_tps"]
    candidate_prompt = candidate["summary"]["median_prompt_tps"]
    baseline_generation = baseline["summary"]["median_generation_tps"]
    candidate_generation = candidate["summary"]["median_generation_tps"]
    prefill_ratio = candidate_prompt / baseline_prompt
    generation_ratio = candidate_generation / baseline_generation
    return {
        "baseline": baseline["label"],
        "candidate": candidate["label"],
        "output_mismatch_samples": mismatches,
        "baseline_median_prompt_tps": baseline_prompt,
        "candidate_median_prompt_tps": candidate_prompt,
        "prefill_speedup_ratio": prefill_ratio,
        "baseline_median_generation_tps": baseline_generation,
        "candidate_median_generation_tps": candidate_generation,
        "generation_speedup_ratio": generation_ratio,
        "minimum_prefill_speedup": minimum_prefill_speedup,
        "maximum_generation_regression": maximum_generation_regression,
        "go": (
            not mismatches
            and prefill_ratio >= minimum_prefill_speedup
            and generation_ratio >= 1.0 - maximum_generation_regression
        ),
    }


def compare(args: argparse.Namespace) -> None:
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    report = comparison_report(
        baseline,
        candidate,
        args.minimum_prefill_speedup,
        args.maximum_generation_regression,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["go"]:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    run_parser.add_argument("--label", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--prompt-tokens", type=int, default=4096)
    run_parser.add_argument("--generation-tokens", type=int, default=128)
    run_parser.add_argument("--samples", type=int, default=3)
    run_parser.add_argument("--timeout", type=int, default=600)
    run_parser.add_argument("--idle-window", type=float, default=20)
    run_parser.add_argument("--idle-timeout", type=float, default=900)
    run_parser.add_argument("--idle-poll-interval", type=float, default=1)
    run_parser.add_argument("--idle-request-timeout", type=int, default=5)
    run_parser.set_defaults(func=run)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("--minimum-prefill-speedup", type=float, default=1.05)
    compare_parser.add_argument("--maximum-generation-regression", type=float, default=0.02)
    compare_parser.set_defaults(func=compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
