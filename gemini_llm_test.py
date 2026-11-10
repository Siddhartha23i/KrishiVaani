"""
Google Gemini Free LLM Provider Evaluation Runner.
Evaluates:
  - gemini-3.8-flash (official model identifier specified in Phase 7.1)

Strict Constraints:
  - Never prints or logs the secret API key.
  - No LangChain, LangGraph, or local hosting.
  - Safe, controlled requests within free-tier quotas.
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List
from dotenv import load_dotenv

# Load environment
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY is not configured in .env")
    sys.exit(1)

CANDIDATE_MODELS = [
    "gemini-3.8-flash",
]

# Standardized Evaluation Prompts
PROMPTS = [
    {
        "name": "Test A — English Reasoning",
        "user_prompt": "Explain the difference between observed rainfall and forecast rainfall in three short points.",
        "system_prompt": None,
        "json_mode": False,
    },
    {
        "name": "Test B — Telugu Understanding",
        "user_prompt": "పరిశీలించిన వర్షపాతం (observed rainfall) మరియు అంచనా వేసిన వర్షపాతం (forecast rainfall) మధ్య గల వ్యత్యాసాన్ని మూడు చిన్న అంశాలలో స్పష్టంగా వివరించండి.",
        "system_prompt": None,
        "json_mode": False,
    },
    {
        "name": "Test C — Structured JSON",
        "user_prompt": "రైతు ప్రశ్న: నా పత్తి చేనులో పురుగు కనిపిస్తోంది, ఏ మందు పిచికారీ చేయాలి?",
        "system_prompt": (
            "You are an agricultural intent extraction system. Return valid JSON only with keys: "
            "intent (string), language (string), required_information (list of strings), "
            "confidence (float between 0.0 and 1.0), response (string)."
        ),
        "json_mode": True,
    },
    {
        "name": "Test D — Farmer Clarification",
        "user_prompt": "My village received very little rainfall recently. I have black soil and limited irrigation water. Which crop should I grow?",
        "system_prompt": (
            "You are an agricultural expert for Telangana farmers. "
            "CRITICAL SAFETY RULE: Never immediately recommend a crop if crucial field parameters are missing. "
            "Identify what essential details are missing (e.g., specific mandal/village, season, land extent, "
            "exact irrigation source, sowing window) and ask concise clarifying questions."
        ),
        "json_mode": False,
    },
    {
        "name": "Test E1 — Evidence-Constrained (Conclusions)",
        "user_prompt": "Based strictly on the provided evidence, explain what can and cannot be concluded.",
        "system_prompt": (
            "You are an agronomic assistant. You must answer STRICTLY based on the provided evidence only. "
            "Do not assume, extrapolate, or invent facts not stated in the evidence.\n\n"
            "PROVIDED EVIDENCE (FICTIONAL TEST DATA ONLY):\n"
            "- Fictional fact 1: The supplied local advisory reports a rainfall observation of 12 mm.\n"
            "- Fictional fact 2: The supplied advisory is valid for the stated observation period only.\n"
            "- No crop recommendation is supplied."
        ),
        "json_mode": False,
    },
    {
        "name": "Test E2 — Evidence-Constrained (Refusal on Missing Advice)",
        "user_prompt": "What pesticide dose should I use?",
        "system_prompt": (
            "You are an agronomic assistant. You must answer STRICTLY based on the provided evidence only. "
            "Do not assume, extrapolate, or invent facts not stated in the evidence.\n\n"
            "PROVIDED EVIDENCE (FICTIONAL TEST DATA ONLY):\n"
            "- Fictional fact 1: The supplied local advisory reports a rainfall observation of 12 mm.\n"
            "- Fictional fact 2: The supplied advisory is valid for the stated observation period only.\n"
            "- No crop recommendation is supplied."
        ),
        "json_mode": False,
    },
    {
        "name": "Test Telugu — Voice-Friendly Agricultural Response",
        "user_prompt": "నాకు రెండు ఎకరాల నల్లరేగడి భూమి ఉంది, బోరు నీళ్లు తక్కువగా ఉన్నాయి, ఈ యాసంగిలో ఏ పంట వేస్తే బాగుంటుంది?",
        "system_prompt": (
            "మీరు తెలంగాణ రైతులకు సహాయం చేసే వ్యవసాయ సలహాదారు. "
            "రైతు మాట్లాడే సహజమైన తెలుగు భాషలో, వినడానికి వీలుగా ఉండే చిన్న మరియు స్పష్టమైన వాక్యాలలో మాత్రమే సమాధానం ఇవ్వండి. "
            "అనవసరమైన ఇంగ్లీష్ పదాలు వాడవద్దు."
        ),
        "json_mode": False,
    },
]


def call_gemini_api(model_id: str, user_prompt: str, system_prompt: str = None, json_mode: bool = False, timeout_s: int = 15) -> Dict[str, Any]:
    """
    Execute request to Gemini REST API endpoint using curl for reliable schannel TLS negotiation on Windows.
    Guarantees API key is NEVER leaked in logs or error messages.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    contents = []
    if system_prompt:
        contents.append({"role": "user", "parts": [{"text": f"System Instructions: {system_prompt}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood. I will strictly adhere to these instructions."}]})
    
    contents.append({"role": "user", "parts": [{"text": user_prompt}]})
    
    payload: Dict[str, Any] = {"contents": contents}
    if json_mode:
        payload["generationConfig"] = {"responseMimeType": "application/json"}

    payload_json = json.dumps(payload)
    cmd = [
        "curl.exe", "-s", "-m", str(timeout_s), "--http1.1",
        "-w", "\n%{http_code}",
        "-H", "Content-Type: application/json",
        "-d", payload_json,
        url
    ]

    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True)
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
            "success": False,
            "http_status": http_code or 504,
            "latency_ms": elapsed_ms,
            "error": f"Curl timeout / network failure (returncode {p.returncode})",
            "content": "",
            "usage": {},
        }

    try:
        data = json.loads(body_str)
    except Exception:
        return {
            "success": False,
            "http_status": http_code,
            "latency_ms": elapsed_ms,
            "error": f"Invalid JSON response: {body_str[:150]}",
            "content": "",
            "usage": {},
        }

    if "error" in data:
        err = data["error"]
        return {
            "success": False,
            "http_status": err.get("code", http_code),
            "latency_ms": elapsed_ms,
            "error": f"{err.get('status', 'ERROR')}: {err.get('message', 'Unknown error')}",
            "content": "",
            "usage": {},
        }

    try:
        candidate = data["candidates"][0]
        text = candidate["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        return {
            "success": True,
            "http_status": 200,
            "latency_ms": elapsed_ms,
            "content": text,
            "usage": usage,
            "finish_reason": candidate.get("finishReason"),
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "http_status": http_code or 500,
            "latency_ms": elapsed_ms,
            "error": f"Malformed candidate structure: {e}",
            "content": "",
            "usage": {},
        }


def run_gemini_eval():
    print("=" * 80)
    print("KRISHIVAANI PHASE 7.1 — GOOGLE GEMINI MODEL EVALUATION")
    print("=" * 80)
    print(f"API Provider: Google Generative AI (Free Tier)")
    print(f"Candidate Models: {', '.join(CANDIDATE_MODELS)}\n")

    results_by_model: Dict[str, List[Dict[str, Any]]] = {}

    for model_id in CANDIDATE_MODELS:
        print(f"\n{'#' * 80}")
        print(f"EVALUATING MODEL: {model_id}")
        print(f"{'#' * 80}")
        model_results = []

        for p in PROMPTS:
            test_name = p["name"]
            print(f"\n--- {test_name} ---")

            res = call_gemini_api(
                model_id=model_id,
                user_prompt=p["user_prompt"],
                system_prompt=p["system_prompt"],
                json_mode=p["json_mode"],
                timeout_s=15,
            )

            test_record = {
                "test_name": test_name,
                "model_id": model_id,
                "success": res["success"],
                "http_status": res["http_status"],
                "latency_ms": res["latency_ms"],
                "usage": res["usage"],
                "finish_reason": res.get("finish_reason"),
                "content": res["content"],
                "reasoning": None,
                "error": res["error"],
            }
            model_results.append(test_record)

            if res["success"]:
                print(f"Status: SUCCESS ({res['latency_ms']:.1f} ms) | HTTP 200")
                print(f"Response:\n{res['content'].strip()}\n")
                if p["json_mode"]:
                    try:
                        parsed = json.loads(res["content"])
                        print(f"  [JSON Check] Valid JSON! Keys: {list(parsed.keys())}")
                    except Exception as je:
                        print(f"  [JSON Check] Invalid JSON: {je}")
            else:
                print(f"Status: FAILED ({res['latency_ms']:.1f} ms) | HTTP {res['http_status']}")
                print(f"Error: {res['error']}")

            time.sleep(1.0)

        results_by_model[model_id] = model_results

    # Output JSON dump
    output_path = Path(__file__).resolve().parent / "gemini_eval_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results_by_model, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed Gemini evaluation results saved to: {output_path.resolve()}")

    return results_by_model


if __name__ == "__main__":
    run_gemini_eval()

