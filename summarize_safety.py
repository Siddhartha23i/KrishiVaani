import json

with open('groq_safety_eval_results.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

for m in d:
    print('=' * 80)
    print(f'MODEL: {m}')
    print('=' * 80)
    tests = d[m]['constrained_tests']
    lats = [t['latency_ms'] for t in tests]
    tokens = [t['usage'].get('total_tokens', 0) for t in tests]
    print(f'Mean Latency: {sum(lats)/len(lats):.1f} ms | Min: {min(lats):.1f} ms | Max: {max(lats):.1f} ms')
    print(f'Total Tokens (all 7 runs): {sum(tokens)} | Avg Tokens/run: {sum(tokens)/len(tokens):.1f}')
    print('-' * 80)
    for t in tests:
        p = t['parsed_json']
        classif = t['safety_eval']['classification']
        pass_fail = 'PASS' if t['safety_eval']['safety_pass'] else 'FAIL'
        lat = t['latency_ms']
        tok = t['usage'].get('total_tokens', 0)
        print(f"[{pass_fail}] {t['title']}")
        print(f"  Classification: {classif} | Latency: {lat:.1f}ms | Tokens: {tok}")
        print(f"  Abstain: {p.get('abstain')} | Schema Valid: {t['safety_eval']['schema_valid']}")
        if t['safety_eval'].get('telugu_score'):
            print(f"  Telugu Score: {t['safety_eval']['telugu_score']}/5")
        resp = p.get('response', '')
        print(f"  Response: {resp[:180]}...")
        if t['safety_eval']['violations']:
            print(f"  Violations: {t['safety_eval']['violations']}")
        if t['safety_eval']['findings']:
            print(f"  Findings: {t['safety_eval']['findings']}")
        print()

