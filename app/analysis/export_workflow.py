"""Generate a Dify 1.17.1 DSL with explicit branches and shared tested Code functions."""
import argparse
import json
from pathlib import Path

from app.analysis.seed_demo import ASSETS


def build_workflow(dataset_id="", base_url="http://host.docker.internal:18086", source_registry=None,
                   knowledge_api_url="http://nginx/v1"):
    code = Path(__file__).with_name("workflow_nodes.py").read_text(encoding="utf-8")
    manifest = source_registry or json.loads((ASSETS / "knowledge_manifest.json").read_text(encoding="utf-8"))
    nodes, edges = [], []

    def add(node_id, node_type, title, **data):
        position = {"x": len(nodes) * 300, "y": 100}
        nodes.append({"id": node_id, "type": "custom", "width": 244, "height": 100,
                      "position": position, "positionAbsolute": position,
                      "sourcePosition": "right", "targetPosition": "left",
                      "data": {"type": node_type, "title": title, "desc": "", "selected": False, **data}})

    def edge(source, target, handle="source"):
        types = {n["id"]: n["data"]["type"] for n in nodes}
        edges.append({"id": f"{source}-{handle}-{target}", "type": "custom", "source": source,
                      "target": target, "sourceHandle": handle, "targetHandle": "target",
                      "data": {"sourceType": types[source], "targetType": types[target],
                               "isInIteration": False, "isInLoop": False}})

    def code_node(node_id, title, variables, call, extra=""):
        args = ", ".join(variables)
        output_types = {
            "state": "string", "result": "string", "query": "string", "heat_id_encoded": "string",
            "scope": "string", "steel_grade": "string", "process_stage": "string", "rule_id": "string",
            "effective_at_epoch": "number",
        }
        add(node_id, "code", title, code_language="python3",
            code=code + "\n" + extra + f"\ndef main({args}):\n    return {call}\n",
            variables=[{"variable": name, "value_selector": selector} for name, selector in variables.items()],
            outputs={name: {"type": kind, "children": None} for name, kind in output_types.items()})

    def branch(node_id, source, state):
        add(node_id, "if-else", "继续条件 / 否则停止", cases=[{"case_id": "true", "logical_operator": "and",
            "conditions": [{"id": node_id + "-condition", "variable_selector": [source, "state"],
                            "comparison_operator": "is", "value": state, "varType": "string"}]}])

    def end(node_id, source):
        add(node_id, "end", "输出结构化结果", outputs=[{"variable": "analysis_result",
            "value_selector": [source, "result"], "value_type": "string"}])

    def http(node_id, title, path):
        add(node_id, "http-request", title, method="get", url=base_url.rstrip("/") + path,
            variables=[], authorization={"type": "no-auth", "config": None}, headers="", params="",
            body={"type": "none", "data": []}, ssl_verify=True,
            timeout={"connect": 5, "read": 10, "write": 5},
            retry_config={"retry_enabled": False, "max_retries": 0, "retry_interval": 100})
        # Dify 1.17.1 discards HTTP response bodies on fail-branch/default-value.
        # Leave both disabled: 4xx/5xx reach the classifier unchanged. Transport
        # failure aborts the workflow and is normalized at the calling boundary.

    add("start", "start", "输入炉次与分析范围", variables=[
        {"variable": "heat_id", "label": "炉次号", "type": "text-input", "required": True, "max_length": 128, "options": []},
        {"variable": "analysis_request", "label": "分析范围", "type": "select", "required": True,
         "options": ["temperature", "chemistry", "all"], "default": "all"}])
    code_node("validate", "参数校验", {"heat_id": ["start", "heat_id"], "analysis_request": ["start", "analysis_request"]},
              "begin(heat_id, analysis_request)")
    branch("valid_branch", "validate", "continue")
    end("invalid_end", "validate")
    http("heat_http", "HTTP 查询 MES 炉次", "/api/mes/heats/{{#validate.heat_id_encoded#}}")
    code_node("heat_check", "炉次不存在 / 失败则停止",
              {"previous": ["validate", "result"], "status_code": ["heat_http", "status_code"], "body": ["heat_http", "body"]},
              "inspect_heat(previous, status_code, body)")
    branch("heat_branch", "heat_check", "continue")
    end("heat_end", "heat_check")
    http("context_http", "HTTP 查询快照与有效规则", "/api/mes/heats/{{#validate.heat_id_encoded#}}/analysis-context")
    code_node("compare", "校验上下文并确定性比较",
              {"previous": ["heat_check", "result"], "status_code": ["context_http", "status_code"], "body": ["context_http", "body"]},
              "compare_context(previous, status_code, body)")
    branch("anomaly_branch", "compare", "retrieve")
    end("facts_end", "compare")
    for node_id in ("catalog_http", "catalog_recheck"):
        http(node_id, "读取完整受控知识目录", "/unused")
        data = nodes[-1]["data"]
        data["url"] = knowledge_api_url.rstrip("/") + f"/datasets/{dataset_id}/documents?page=1&limit=100"
        data["headers"] = "Authorization:Bearer {{#env.KNOWLEDGE_API_KEY#}}"
    code_node("catalog_check", "版本冲突 / 缺失来源则停止",
              {"previous": ["compare", "result"], "status_code": ["catalog_http", "status_code"],
               "body": ["catalog_http", "body"]},
              "inspect_catalog(previous, status_code, body, MANIFEST)", extra="MANIFEST = " + repr(manifest))
    branch("catalog_branch", "catalog_check", "retrieve")
    end("catalog_end", "catalog_check")
    add("retrieval", "knowledge-retrieval", "仅异常分支检索正式规程",
        query_variable_selector=["compare", "query"], query_attachment_selector=[],
        dataset_ids=[dataset_id] if dataset_id else [], retrieval_mode="multiple",
        multiple_retrieval_config={"top_k": 8, "score_threshold": None, "reranking_enable": False,
                                   "reranking_mode": "reranking_model"},
        metadata_filtering_mode="manual",
        metadata_filtering_conditions={"logical_operator": "and", "conditions": [
            {"id": "status", "name": "status", "comparison_operator": "is", "value": "active"},
            {"id": "scope", "name": "scope", "comparison_operator": "is", "value": "{{#compare.scope#}}"},
            {"id": "steel_grade", "name": "steel_grade", "comparison_operator": "is", "value": "{{#compare.steel_grade#}}"},
            {"id": "process_stage", "name": "process_stage", "comparison_operator": "is", "value": "{{#compare.process_stage#}}"},
            {"id": "rule_id", "name": "rule_id", "comparison_operator": "is", "value": "{{#compare.rule_id#}}"},
            {"id": "effective_from", "name": "effective_from", "comparison_operator": "≤", "value": "{{#compare.effective_at_epoch#}}"},
            {"id": "effective_until", "name": "effective_until", "comparison_operator": ">", "value": "{{#compare.effective_at_epoch#}}"},
            {"id": "document_id", "name": "document_id", "comparison_operator": "not empty", "value": None},
            {"id": "version", "name": "version", "comparison_operator": "not empty", "value": None},
            {"id": "effective_date", "name": "effective_date", "comparison_operator": "not empty", "value": None},
            {"id": "chapter", "name": "chapter", "comparison_operator": "not empty", "value": None},
            {"id": "section", "name": "section", "comparison_operator": "not empty", "value": None},
            {"id": "content_sha256", "name": "content_sha256", "comparison_operator": "not empty", "value": None},
        ]},
        error_strategy="fail-branch")
    code_node("evidence", "Evidence First 与六项报告",
              {"previous": ["catalog_check", "result"], "retrieval_result": ["retrieval", "result"],
               "status_code": ["catalog_recheck", "status_code"], "body": ["catalog_recheck", "body"]},
              "evidence_with_catalog(previous, retrieval_result, status_code, body, MANIFEST)",
              extra="MANIFEST = " + repr(manifest))
    end("report_end", "evidence")
    for source, previous in [("retrieval", "compare")]:
        failure = source + "_failure"
        code_node(failure, "系统失败 / 人工确认", {"previous": [previous, "result"]},
                  f"transport_failure(previous, {source!r})")
        end(failure + "_end", failure)
        edge(source, failure, "fail-branch")
        edge(failure, failure + "_end")
    for source, target, handle in [
        ("start", "validate", "source"), ("validate", "valid_branch", "source"),
        ("valid_branch", "invalid_end", "false"), ("valid_branch", "heat_http", "true"),
        ("heat_http", "heat_check", "source"), ("heat_check", "heat_branch", "source"),
        ("heat_branch", "heat_end", "false"), ("heat_branch", "context_http", "true"),
        ("context_http", "compare", "source"), ("compare", "anomaly_branch", "source"),
        ("anomaly_branch", "facts_end", "false"), ("anomaly_branch", "catalog_http", "true"),
        ("catalog_http", "catalog_check", "source"), ("catalog_check", "catalog_branch", "source"),
        ("catalog_branch", "catalog_end", "false"), ("catalog_branch", "retrieval", "true"),
        ("retrieval", "catalog_recheck", "source"), ("catalog_recheck", "evidence", "source"),
        ("evidence", "report_end", "source")]:
        edge(source, target, handle)
    # Keep stop outputs below the main path so the imported graph is readable.
    positions = {
        "start": (0, 0), "validate": (300, 0), "valid_branch": (600, 0),
        "invalid_end": (600, 240), "heat_http": (900, 0), "heat_check": (1200, 0),
        "heat_branch": (1500, 0), "heat_end": (1500, 240), "context_http": (1800, 0),
        "compare": (2100, 0), "anomaly_branch": (2400, 0), "facts_end": (2400, 240),
        "catalog_http": (2700, 0), "catalog_check": (3000, 0), "catalog_branch": (3300, 0),
        "catalog_end": (3300, 240), "retrieval": (3600, 0), "catalog_recheck": (3900, 0),
        "evidence": (4200, 0), "report_end": (4500, 0),
        "retrieval_failure": (4200, 240), "retrieval_failure_end": (4500, 240),
    }
    for node in nodes:
        x, y = positions[node["id"]]
        node["position"] = node["positionAbsolute"] = {"x": x, "y": y}
    return {"version": "0.7.0", "kind": "app", "dependencies": [],
            "app": {"name": "制造业异常分析闭环-任务06", "description": "虚构 PoC；显式 Workflow、Source of Truth、Evidence First；无自动设备动作。",
                    "mode": "workflow", "icon": "🏭", "icon_background": "#E4FBCC", "use_icon_as_answer_icon": False},
            "workflow": {"conversation_variables": [], "environment_variables": [
                         {"id": "3edc8a00-30d0-4000-8000-000000000001", "name": "KNOWLEDGE_API_KEY",
                          "value": "", "value_type": "secret", "selector": ["env", "KNOWLEDGE_API_KEY"]}],
                         "features": {"file_upload": {"enabled": False}, "retriever_resource": {"enabled": True}},
                         "graph": {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.5}}}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", default="")
    parser.add_argument("--base-url", default="http://host.docker.internal:18086")
    parser.add_argument("--source-registry", type=Path)
    parser.add_argument("--output", type=Path, default=Path("workflows/heat_analysis.yml"))
    args = parser.parse_args()
    registry = json.loads(args.source_registry.read_text(encoding="utf-8")) if args.source_registry else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # JSON is a YAML-compatible serialization accepted by Dify's YAML loader.
    args.output.write_text(json.dumps(build_workflow(args.dataset_id, args.base_url, registry), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported DSL: {args.output}")
