"""Run offline annotated scenarios; no search, embedding, Dify or LLM calls."""
import json
from pathlib import Path

from app.evidence.gate import evaluate

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "rag_demo"


def main() -> None:
    corpus = json.loads((ASSETS / "corpus.json").read_text(encoding="utf-8"))
    scenarios = json.loads((ASSETS / "questions.json").read_text(encoding="utf-8"))
    failures = []
    for scenario in scenarios:
        result = evaluate(corpus, scenario["request"])
        expected = scenario["expected"]
        passed = (result.decision == expected["decision"]
                  and result.reason_codes == expected["reason_codes"]
                  and [e.chunk_id for e in result.evidence] == expected["evidence_chunk_ids"])
        print(f"{'PASS' if passed else 'FAIL'} {scenario['id']}: {result.decision} / {','.join(result.reason_codes)}")
        if not passed:
            failures.append(scenario["id"])
    if failures:
        raise SystemExit(f"Failed: {failures}")


if __name__ == "__main__":
    main()
