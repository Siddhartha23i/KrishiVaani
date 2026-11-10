"""
Groq Free LLM Provider & Reasoning Model Evaluation Runner.
Evaluates:
  1. openai/gpt-oss-120b
  2. openai/gpt-oss-20b
  3. qwen/qwen3.8-27b

Strict Constraints:
  - Never prints or logs the secret API key.
  - No LangChain, LangGraph, or local hosting.
  - Safe, controlled requests within free-tier quotas.
"""

import os
import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List
from dotenv import load_dotenv

# Load environment
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("ERROR: GROQ_API_KEY is not configured in .env")
    sys.exit(1)

from groq import Groq

# Initialize client
client = Groq(api_key=GROQ_API_KEY)

CANDIDATE_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

# Standardized Evaluation Prompts
PROMPT_TEST_A = {
    "name": "Test A — English Reasoning",
    "messages": [
        {
            "role": "user",
            "content": "Explain the difference between observed rainfall and forecast rainfall in three short points."
        }
    ],
    "response_format": None,
    "max_tokens": 400,
}

PROMPT_TEST_B = {
    "name": "Test B — Telugu Understanding",
    "messages": [
        {
            "role": "user",
            "content": "పరిశీలించిన వర్షపాతం (observed rainfall) మరియు అంచనా వేసిన వర్షపాతం (forecast rainfall) మధ్య గల వ్యత్యాసాన్ని మూడు చిన్న అంశాలలో స్పష్టంగా వివరించండి."
        }
    ],
    "response_format": None,
    "max_tokens": 450,
}

PROMPT_TEST_C = {
    "name": "Test C — Structured JSON",
    "messages": [
        {
            "role": "system",
            "content": (
                "You are an agricultural intent extraction system. Return valid JSON only with keys: "
                "intent (string), language (string), required_information (list of strings), "
                "confidence (float between 0.0 and 1.0), response (string)."
            )
        },
        {
            "role": "user",
            "content": "రైతు ప్రశ్న: నా పత్తి చేనులో పురుగు కనిపిస్తోంది, ఏ మందు పిచికారీ చేయాలి?"
        }
    ],
    "response_format": {"type": "json_object"},
    "max_tokens": 450,
}

PROMPT_TEST_D = {
    "name": "Test D — Farmer Clarification",
    "messages": [
        {
            "role": "system",
            "content": (
                "You are an agricultural expert for Telangana farmers. "
                "CRITICAL SAFETY RULE: Never immediately recommend a crop if crucial field parameters are missing. "
                "Identify what essential details are missing (e.g., specific mandal/village, season, land extent, "
                "exact irrigation source, sowing window) and ask concise clarifying questions."
            )
        },
        {
            "role": "user",
            "content": (
                "My village received very little rainfall recently. I have black soil and limited irrigation water. "
                "Which crop should I grow?"
            )
        }
    ],
    "response_format": None,
    "max_tokens": 500,
}

PROMPT_TEST_E1 = {
    "name": "Test E1 — Evidence-Constrained (Conclusions)",
    "messages": [
        {
            "role": "system",
            "content": (
                "You are an agronomic assistant. You must answer STRICTLY based on the provided evidence only. "
                "Do not assume, extrapolate, or invent facts not stated in the evidence.\n\n"
                "PROVIDED EVIDENCE (FICTIONAL TEST DATA ONLY):\n"
                "- Fictional fact 1: The supplied local advisory reports a rainfall observation of 12 mm.\n"
                "- Fictional fact 2: The supplied advisory is valid for the stated observation period only.\n"
                "- No crop recommendation is supplied."
            )
        },
        {
            "role": "user",
            "content": "Based strictly on the provided evidence, explain what can and cannot be concluded."
        }
    ],
    "response_format": None,
    "max_tokens": 400,
}

PROMPT_TEST_E2 = {
    "name": "Test E2 — Evidence-Constrained (Refusal on Missing Advice)",
    "messages": [
        {
            "role": "system",
            "content": (
                "You are an agronomic assistant. You must answer STRICTLY based on the provided evidence only. "
                "Do not assume, extrapolate, or invent facts not stated in the evidence.\n\n"
                "PROVIDED EVIDENCE (FICTIONAL TEST DATA ONLY):\n"
                "- Fictional fact 1: The supplied local advisory reports a rainfall observation of 12 mm.\n"
                "- Fictional fact 2: The supplied advisory is valid for the stated observation period only.\n"
                "- No crop recommendation is supplied."
            )
        },
        {
            "role": "user",
            "content": "What pesticide dose should I use?"
        }
    ],
    "response_format": None,
    "max_tokens": 300,
}

PROMPT_TEST_TELUGU_VOICE = {
    "name": "Test Telugu — Voice-Friendly Agricultural Response",
    "messages": [
        {
            "role": "system",
            "content": (
                "మీరు తెలంగాణ రైతులకు సహాయం చేసే వ్యవసాయ సలహాదారు. "
                "రైతు మాట్లాడే సహజమైన తెలుగు భాషలో, వినడానికి వీలుగా ఉండే చిన్న మరియు స్పష్టమైన వాక్యాలలో మాత్రమే సమాధానం ఇవ్వండి. "
                "అనవసరమైన ఇంగ్లీష్ పదాలు వాడవద్దు."
            )
        },
        {
            "role": "user",
            "content": "నాకు రెండు ఎకరాల నల్లరేగడి భూమి ఉంది, బోరు నీళ్లు తక్కువగా ఉన్నాయి, ఈ యాసంగిలో ఏ పంట వేస్తే బాగుంటుంది?"
        }
    ],
    "response_format": None,
    "max_tokens": 400,
}

ALL_TEST_PROMPTS = [
    PROMPT_TEST_A,
    PROMPT_TEST_B,
    PROMPT_TEST_C,
    PROMPT_TEST_D,
    PROMPT_TEST_E1,
    PROMPT_TEST_E2,
    PROMPT_TEST_TELUGU_VOICE,
]


def run_groq_eval():
    print("=" * 80)
    print("KRISHIVAANI PHASE 7.1 — GROQ REASONING MODEL EVALUATION")
    print("=" * 80)
    print(f"API Provider: Groq Cloud (Free Tier)")
    print(f"Candidate Models ({len(CANDIDATE_MODELS)}): {', '.join(CANDIDATE_MODELS)}\n")

    results_by_model: Dict[str, List[Dict[str, Any]]] = {}

    for model_id in CANDIDATE_MODELS:
        print(f"\n{'#' * 80}")
        print(f"EVALUATING MODEL: {model_id}")
        print(f"{'#' * 80}")
        model_results = []

        for p in ALL_TEST_PROMPTS:
            test_name = p["name"]
            print(f"\n--- {test_name} ---")

            kwargs: Dict[str, Any] = {
                "model": model_id,
                "messages": p["messages"],
                "max_tokens": p["max_tokens"],
                "temperature": 0.0,
            }
            if p["response_format"]:
                kwargs["response_format"] = p["response_format"]

            start_t = time.perf_counter()
            success = False
            http_status = 200
            err_msg = None
            content = ""
            reasoning = None
            usage_dict = {}
            finish_reason = None

            try:
                res = client.chat.completions.create(**kwargs)
                elapsed_ms = (time.perf_counter() - start_t) * 1000
                success = True
                choice = res.choices[0]
                finish_reason = choice.finish_reason
                msg = choice.message
                content = msg.content or ""
                reasoning = getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None)
                if res.usage:
                    usage_dict = {
                        "prompt_tokens": res.usage.prompt_tokens,
                        "completion_tokens": res.usage.completion_tokens,
                        "total_tokens": res.usage.total_tokens,
                    }

                print(f"Status: SUCCESS ({elapsed_ms:.1f} ms) | Finish: {finish_reason}")
                print(f"Tokens: Prompt={usage_dict.get('prompt_tokens')}, Completion={usage_dict.get('completion_tokens')}")
                if reasoning:
                    print(f"Reasoning ({len(reasoning)} chars): {reasoning[:120]}...")
                print(f"Response:\n{content.strip()}\n")

                # Verify JSON structure for Test C
                if "JSON" in test_name:
                    try:
                        parsed = json.loads(content)
                        keys = list(parsed.keys())
                        print(f"  [JSON Check] Valid JSON! Keys: {keys}")
                    except Exception as json_err:
                        print(f"  [JSON Check] FAILED TO PARSE JSON: {json_err}")

            except Exception as e:
                elapsed_ms = (time.perf_counter() - start_t) * 1000
                err_msg = f"{type(e).__name__}: {e}"
                print(f"Status: FAILED ({elapsed_ms:.1f} ms): {err_msg}")
                http_status = getattr(e, "status_code", 500)

            # Record metrics
            test_record = {
                "test_name": test_name,
                "model_id": model_id,
                "success": success,
                "http_status": http_status,
                "latency_ms": elapsed_ms,
                "usage": usage_dict,
                "finish_reason": finish_reason,
                "content": content,
                "reasoning": reasoning,
                "error": err_msg,
            }
            model_results.append(test_record)

            # Modest pacing between requests to stay well within free RPM/TPM limits
            time.sleep(1.0)

        results_by_model[model_id] = model_results

    # Summary Table
    print("\n" + "=" * 80)
    print("GROQ EVALUATION SUMMARY METRICS")
    print("=" * 80)
    for model_id, res_list in results_by_model.items():
        success_count = sum(1 for r in res_list if r["success"])
        avg_latency = sum(r["latency_ms"] for r in res_list) / len(res_list) if res_list else 0
        total_tokens = sum(r["usage"].get("total_tokens", 0) for r in res_list)
        print(f"Model: {model_id:25} | Passed: {success_count}/{len(res_list)} | Avg Latency: {avg_latency:.1f}ms | Total Tokens: {total_tokens}")

    # Output JSON dump
    output_path = Path(__file__).resolve().parent / "groq_eval_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results_by_model, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed evaluation results saved to: {output_path.resolve()}")

    return results_by_model


if __name__ == "__main__":
    run_groq_eval()

