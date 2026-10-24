import httpx

r = httpx.get('http://localhost:8001/api/v1/evaluations/runs')
runs = r.json()
print('Total runs:', len(runs))
if runs:
    latest = runs[0]
    rid = latest['id']
    print('Latest Run ID:', rid)
    print('Status:', latest['status'])
    print('Successful executions:', latest.get('successful_executions'))
    print('Correct results:', latest.get('correct_results'))
    d = httpx.get(f'http://localhost:8001/api/v1/evaluations/runs/{rid}').json()
    results = d.get('results', [])
    print('Cases completed:', len(results))
    for i, res in enumerate(results, 1):
        q = res['question'][:45]
        corr = res['result_correct']
        out = res['policy_outcome']
        lat = round(res['latency_ms']) if res.get('latency_ms') else 0
        print(f"[{i:2d}/31] {out:18s} | correct={str(corr):5s} | {lat:5d}ms | {q}")
