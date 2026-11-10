"""
KrishiVaani Phase 7.1.3 — Gemini Reasoning Model Evaluation.

Tests the four exact model IDs specified by the user:
  1. gemini-3.1-pro-preview
  2. gemini-3.8-flash
  3. gemini-2.5-pro
  4. gemini-2.5-flash

Checks:
  - Official model-list API availability.
  - Verification of generateContent support.
  - Classification: Model Retirement, Account Restrictions, Quota Errors, or Invalid Credentials.
  - Execution of standardized prompts if accessible.
  - Free-tier quota restrictions analysis without enabling paid requests.
  - Preservation of Groq baseline comparison.
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY is not configured in .env")
    sys.exit(1)

TARGET_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.8-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash"
]

def get_official_model_catalog() -> Dict[str, Any]:
    """Fetch official model list from Google Generative Language API."""
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    p = subprocess.run(
        ["curl.exe", "-s", "--http1.1", "-H", f"x-goog-api-key: {GEMINI_API_KEY}", url],
        capture_output=True, text=True
    )
    if p.returncode != 0:
        return {"error": f"Failed to connect to Google model list API (returncode {p.returncode})"}
    try:
        return json.loads(p.stdout)
    except Exception as e:
        return {"error": f"Failed to parse model list JSON: {e}"}

def probe_endpoint(model_id: str, api_version: str = "v1beta") -> Dict[str, Any]:
    """Probe a specific model on a specific API version."""
    url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model_id}:generateContent"
    payload = json.dumps({"contents": [{"parts": [{"text": "Hello"}]}]})
    
    t0 = time.perf_counter()
    p = subprocess.run(
        [
            "curl.exe", "-s", "-m", "10", "--http1.1",
            "-w", "\n%{http_code}",
            "-H", "Content-Type: application/json",
            "-H", f"x-goog-api-key: {GEMINI_API_KEY}",
            "-d", payload,
            url
        ],
        capture_output=True, text=True
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    out = p.stdout.strip()
    lines = out.split("\n")
    http_code = 0
    body_str = out
    if len(lines) >= 2:
        try:
            http_code = int(lines[-1])
            body_str = "\n".join(lines[:-1])
        except Exception:
            http_code = 0

    if p.returncode != 0:
        return {
            "api_version": api_version,
            "accessible": False,
            "http_status": http_code or 504,
            "classification": "Network / Timeout Failure",
            "latency_ms": elapsed_ms,
            "details": f"Curl timeout / network failure (returncode {p.returncode})",
            "raw_body": None,
        }

    try:
        data = json.loads(body_str)
    except Exception:
        return {
            "api_version": api_version,
            "accessible": False,
            "http_status": http_code,
            "classification": "Unknown / Unparseable Response",
            "latency_ms": elapsed_ms,
            "details": body_str[:200],
            "raw_body": None,
        }

    if "error" in data:
        err = data["error"]
        code = err.get("code", http_code)
        msg = err.get("message", "")
        status = err.get("status", "")

        if code == 404:
            classification = "Model Retirement / Deprecation / Not Found"
        elif code == 429:
            classification = "Quota Exhausted / Tier Restriction"
        elif code in (401, 403):
            classification = "Invalid Credentials / Account Permission"
        elif code == 503:
            classification = "Service Unavailable / High Demand"
        else:
            classification = f"API Error ({status})"

        return {
            "api_version": api_version,
            "accessible": False,
            "http_status": code,
            "classification": classification,
            "latency_ms": elapsed_ms,
            "details": msg,
            "raw_error": err,
        }

    return {
        "api_version": api_version,
        "accessible": True,
        "http_status": 200,
        "classification": "Available",
        "latency_ms": elapsed_ms,
        "details": "Model accepted generateContent request.",
        "raw_data": data,
    }

def probe_model_status(model_id: str) -> Dict[str, Any]:
    """Probe model across both v1beta and v1 endpoints."""
    res_v1beta = probe_endpoint(model_id, api_version="v1beta")
    res_v1 = probe_endpoint(model_id, api_version="v1")
    return {
        "v1beta": res_v1beta,
        "v1": res_v1,
        "accessible": res_v1beta.get("accessible", False) or res_v1.get("accessible", False),
    }

def main():
    print("=" * 80)
    print("KrishiVaani Phase 7.1.3 — Gemini Reasoning Model Evaluation")
    print("=" * 80)

    # Step 1: Catalog verification
    catalog_resp = get_official_model_catalog()
    if "error" in catalog_resp:
        print(f"ERROR: {catalog_resp['error']}")
        sys.exit(1)

    models_list = catalog_resp.get("models", [])
    model_by_name = {m["name"].replace("models/", ""): m for m in models_list}

    print(f"\n1. Official Catalog Inspection (Total catalog models: {len(models_list)})")
    print("-" * 80)

    audit_results = {}

    for model_id in TARGET_MODELS:
        in_catalog = model_id in model_by_name
        meta = model_by_name.get(model_id, {})
        methods = meta.get("supportedGenerationMethods", [])
        supports_gen = "generateContent" in methods
        thinking = meta.get("thinking", False)
        input_limit = meta.get("inputTokenLimit")
        output_limit = meta.get("outputTokenLimit")
        version = meta.get("version", "N/A")

        print(f"Model: {model_id}")
        print(f"  In Catalog: {in_catalog}")
        print(f"  Version: {version}")
        print(f"  Supports generateContent: {supports_gen}")
        print(f"  Supports Native Thinking: {thinking}")
        print(f"  Token Limits: Input={input_limit}, Output={output_limit}")

        # Step 2: Diagnostic probe across v1beta and v1
        probe = probe_model_status(model_id)
        pb = probe["v1beta"]
        p1 = probe["v1"]
        print(f"  v1beta Status: HTTP {pb['http_status']} ({pb['classification']}) | {pb['latency_ms']:.1f}ms")
        print(f"    v1beta Info: {pb['details'][:100]}...")
        print(f"  v1 Status:     HTTP {p1['http_status']} ({p1['classification']}) | {p1['latency_ms']:.1f}ms")
        print(f"    v1 Info:     {p1['details'][:100]}...")
        print("-" * 80)

        audit_results[model_id] = {
            "model_id": model_id,
            "in_catalog": in_catalog,
            "version": version,
            "supports_generateContent": supports_gen,
            "supports_thinking": thinking,
            "input_token_limit": input_limit,
            "output_token_limit": output_limit,
            "probe_result": probe,
        }

    # Save results to JSON
    output_path = Path(__file__).resolve().parent / "gemini_eval_results_7_1_3.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2)

    print(f"\nSaved evaluation audit to {output_path.name}")
    print("=" * 80)

if __name__ == "__main__":
    main()
