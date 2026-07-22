import unittest
from unittest import mock

from llm_ops.vulkan import benchmark_vulkan as benchmark
from llm_ops.vulkan.benchmark_vulkan import (
    active_slot_count,
    comparison_report,
    forced_output_grammar,
    summarize,
    wait_for_idle_window,
)


def artifact(label, prompt_tps, generation_tps, digest="same"):
    return {
        "label": label,
        "summary": {
            "median_prompt_tps": prompt_tps,
            "median_generation_tps": generation_tps,
        },
        "results": [{"sample": 1, "output_sha256": digest}],
    }


class BenchmarkTests(unittest.TestCase):
    def test_active_slot_count_rejects_busy_slots(self):
        self.assertEqual(
            active_slot_count(
                [
                    {"id": 0, "is_processing": False},
                    {"id": 1, "is_processing": True},
                ]
            ),
            1,
        )
        self.assertEqual(active_slot_count([]), 0)
        with self.assertRaises(ValueError):
            active_slot_count({"is_processing": False})

    def test_idle_window_restarts_after_a_busy_slot(self):
        now = [0.0]
        responses = [
            [{"is_processing": False}],
            [{"is_processing": True}],
            [{"is_processing": False}],
            [{"is_processing": False}],
            [{"is_processing": False}],
        ]

        def sleep(seconds):
            now[0] += seconds

        with mock.patch.object(
            benchmark.time, "monotonic", side_effect=lambda: now[0]
        ), mock.patch.object(benchmark.time, "sleep", side_effect=sleep), mock.patch.object(
            benchmark, "request_json", side_effect=responses
        ) as request:
            wait_for_idle_window("http://test", 1, 10, 1, 1)

        self.assertEqual(request.call_count, 5)

    def test_forced_grammar_is_longer_than_the_decode(self):
        grammar = forced_output_grammar(128)
        self.assertTrue(grammar.startswith('root ::= "'))
        self.assertGreater(grammar.count(" 0"), 128)

    def test_summarize_uses_medians(self):
        summary = summarize(
            [
                {"prompt_per_second": 10, "predicted_per_second": 5, "wall_seconds": 2},
                {"prompt_per_second": 30, "predicted_per_second": 7, "wall_seconds": 3},
                {"prompt_per_second": 20, "predicted_per_second": 6, "wall_seconds": 4},
            ]
        )
        self.assertEqual(summary["median_prompt_tps"], 20)
        self.assertEqual(summary["median_generation_tps"], 6)
        self.assertEqual(summary["total_wall_seconds"], 9)

    def test_go_requires_speedup_stable_generation_and_equal_output(self):
        report = comparison_report(
            artifact("base", 100, 10), artifact("candidate", 108, 9.9), 1.05, 0.02
        )
        self.assertTrue(report["go"])

        mismatch = comparison_report(
            artifact("base", 100, 10),
            artifact("candidate", 108, 9.9, digest="different"),
            1.05,
            0.02,
        )
        self.assertFalse(mismatch["go"])

        regression = comparison_report(
            artifact("base", 100, 10), artifact("candidate", 108, 9.7), 1.05, 0.02
        )
        self.assertFalse(regression["go"])


if __name__ == "__main__":
    unittest.main()
