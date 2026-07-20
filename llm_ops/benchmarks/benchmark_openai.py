#!/usr/bin/env python3
"""Deterministic text benchmark for baseline/MTP llama-server profiles."""

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path


PROMPTS = [
    "Кратко объясни в 4 пунктах, зачем проверять доказательства перед включением OCR-текста в train dataset.",
    "Извлеки поля в одной строке JSON: счет №A-418, дата 14.07.2026, сумма 19375 RUB, поставщик Сокол ООО.",
    "Переведи на русский и объясни одним предложением: Speculative decoding must preserve target-model verification.",
    "Дай пять последовательных шагов безопасного отката LLM-сервиса после неудачного обновления.",
    "Напиши компактную функцию Python normalize_spaces(text), заменяющую серии пробельных символов одним пробелом.",
    "Реши и кратко проверь: склад получил 17 коробок по 24 детали, затем отгрузил 139 деталей. Сколько осталось?",
    "Объясни декларанту разницу между документом-источником, OCR silver candidate и вручную проверенной записью.",
    "Верни только JSON с ключами code и amount: код SOKOL-4827, сумма 19 375 рублей.",
    "Составь короткий чек-лист проверки двух GPU: память, загрузка, сеть RPC, ошибки драйвера, health endpoint.",
    "У Анны, Бориса и Веры разные роли: аналитик, инженер, юрист. Анна не инженер, Борис не юрист, Вера аналитик. Кто кем работает? Объясни кратко.",
]


def request_json(url, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def run(args):
    results = []
    endpoint = args.base_url.rstrip("/") + "/v1/chat/completions"
    for index, prompt in enumerate(PROMPTS, start=1):
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "top_k": 1,
            "seed": 42,
            "max_tokens": args.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        started = time.monotonic()
        response = request_json(endpoint, payload, args.timeout)
        wall_seconds = time.monotonic() - started
        choice = response["choices"][0]
        timings = response.get("timings", {})
        record = {
            "case": index,
            "prompt": prompt,
            "content": choice["message"].get("content", ""),
            "finish_reason": choice.get("finish_reason"),
            "completion_tokens": response.get("usage", {}).get("completion_tokens"),
            "wall_seconds": wall_seconds,
            "predicted_tps": timings.get("predicted_per_second"),
        }
        results.append(record)
        print(
            f"case={index:02d} tokens={record['completion_tokens']} "
            f"tps={record['predicted_tps']:.3f} wall={wall_seconds:.3f}s",
            flush=True,
        )

    tps = [item["predicted_tps"] for item in results if item["predicted_tps"]]
    artifact = {
        "label": args.label,
        "base_url": args.base_url,
        "determinism": {
            "temperature": 0,
            "top_k": 1,
            "seed": 42,
            "thinking": False,
        },
        "summary": {
            "cases": len(results),
            "median_predicted_tps": statistics.median(tps),
            "mean_predicted_tps": statistics.fmean(tps),
            "total_wall_seconds": sum(item["wall_seconds"] for item in results),
        },
        "results": results,
    }
    Path(args.output).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False), flush=True)


def compare(args):
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    baseline_by_case = {item["case"]: item for item in baseline["results"]}
    mismatches = []
    for item in candidate["results"]:
        original = baseline_by_case[item["case"]]
        if item["content"] != original["content"]:
            mismatches.append(item["case"])
    baseline_tps = baseline["summary"]["median_predicted_tps"]
    candidate_tps = candidate["summary"]["median_predicted_tps"]
    report = {
        "baseline": baseline["label"],
        "candidate": candidate["label"],
        "cases": len(candidate["results"]),
        "exact_output_mismatches": mismatches,
        "baseline_median_tps": baseline_tps,
        "candidate_median_tps": candidate_tps,
        "median_speedup_ratio": candidate_tps / baseline_tps,
        "go": not mismatches and candidate_tps >= baseline_tps * 1.05,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if mismatches:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    run_parser.add_argument("--label", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--max-tokens", type=int, default=192)
    run_parser.add_argument("--timeout", type=int, default=300)
    run_parser.set_defaults(func=run)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.set_defaults(func=compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
