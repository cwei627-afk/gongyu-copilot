"""Reference execution of explicit workflow steps through real HTTP (no local DB reads)."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from app.analysis import workflow_nodes as nodes

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "analysis_demo"


def run(heat_id, analysis_request, get, retrieve, manifest):
    step = nodes.begin(heat_id, analysis_request)
    if step["state"] == "end":
        return json.loads(step["result"])
    for suffix, handler in [("", nodes.inspect_heat), ("/analysis-context", nodes.compare_context)]:
        try:
            status, body = get(f"/api/mes/heats/{step['heat_id_encoded']}{suffix}")
        except (TimeoutError, OSError):
            step = nodes.transport_failure(step["result"], "mes")
            break
        step = handler(step["result"], status, body)
        if step["state"] == "end":
            break
    if step["state"] == "retrieve":
        try:
            candidates = retrieve(step["query"])
        except (TimeoutError, OSError):
            step = nodes.evidence_decision(step["result"], [], manifest, retrieval_failed=True)
        else:
            step = nodes.evidence_decision(step["result"], candidates, manifest)
    return json.loads(step["result"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("heat_id")
    parser.add_argument("--analysis", choices=["temperature", "chemistry", "all"], default="all")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--evidence", choices=["fixture", "none", "related", "failure"], default="fixture")
    args = parser.parse_args()
    manifest = json.loads((ASSETS / "knowledge_manifest.json").read_text(encoding="utf-8"))

    def get(path):
        try:
            with urlopen(args.base_url.rstrip("/") + path, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def retrieve(query):
        # Explicit fixture transport, never presented as measured RAG retrieval quality.
        if args.evidence == "failure":
            raise TimeoutError("simulated retrieval failure")
        if args.evidence == "none":
            return []
        if args.evidence == "related":
            return [{"content": "温度记录需要填写炉次号和测量时间。"}]
        return [nodes.controlled_fixture_hit(document) for document in manifest["documents"]]

    print(json.dumps(run(args.heat_id, args.analysis, get, retrieve, manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
