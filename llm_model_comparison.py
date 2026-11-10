"""
KrishiVaani Phase 7.1 — Model Comparison and Metric Aggregator.

Loads evaluation test results from groq_eval_results.json and gemini_eval_results.json,
computes comparative metrics, and prints structured evaluation benchmarks.
"""

import json
import os
import sys

def load_results():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    groq_file = os.path.join(base_dir, "groq_eval_results.json")
    gemini_file = os.path.join(base_dir, "gemini_eval_results.json")

    groq_data = {}
    gemini_data = {}

    if os.path.exists(groq_file):
        with open(groq_file, "r", encoding="utf-8") as f:
            groq_data = json.load(f)

    if os.path.exists(gemini_file):
        with open(gemini_file, "r", encoding="utf-8") as f:
            gemini_data = json.load(f)

    combined = {}
    combined.update(groq_data)
    combined.update(gemini_data)
    return combined

def analyze():
    data = load_results()
    if not data:
        print("No evaluation data found.")
        return

    print("=" * 110)
    print(f"{'Model Identifier':<24} | {'Test A (ms)':<11} | {'Test B (ms)':<11} | {'Test C (ms)':<11} | {'Test D (ms)':<11} | {'Test E1 (ms)':<12} | {'Test E2 (ms)':<12} | {'Avg Latency':<12}")
    print("-" * 110)

    summary = {}

    for model, tests in data.items():
        latencies = [t["latency_ms"] for t in tests]
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        success_count = sum(1 for t in tests if t.get("success", False))

        lat_by_test = {t["test_name"]: t["latency_ms"] for t in tests}

        test_a = lat_by_test.get("Test A — English Reasoning", 0)
        test_b = lat_by_test.get("Test B — Telugu Understanding", 0)
        test_c = lat_by_test.get("Test C — Structured JSON", 0)
        test_d = lat_by_test.get("Test D — Farmer Clarification", 0)
        test_e1 = lat_by_test.get("Test E1 — Evidence-Constrained (Conclusions)", 0)
        test_e2 = lat_by_test.get("Test E2 — Evidence-Constrained (Refusal on Missing Advice)", 0)

        print(f"{model:<24} | {test_a:<11.1f} | {test_b:<11.1f} | {test_c:<11.1f} | {test_d:<11.1f} | {test_e1:<12.1f} | {test_e2:<12.1f} | {avg_lat:<12.1f}")

        summary[model] = {
            "success_rate": f"{success_count}/{len(tests)}",
            "avg_latency_ms": round(avg_lat, 1),
            "latencies": lat_by_test
        }

    print("=" * 110)
    return summary

if __name__ == "__main__":
    analyze()

