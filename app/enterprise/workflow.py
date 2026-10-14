"""Compose Stage C on frozen A/B builders; do not alter their implementation."""
import argparse
import json
import re
from pathlib import Path

from app.analysis.generation_workflow import build_generation_workflow
from app.enterprise.nodes import ENTERPRISE_MODEL_SCHEMA


def build_enterprise_workflow(dataset_id, base_url, registry):
    dsl = build_generation_workflow(dataset_id, base_url, registry)
    graph = dsl["workflow"]["graph"]
    root = Path(__file__).resolve().parents[1]
    source = (root / "enterprise/nodes.py").read_text(encoding="utf-8")
    source = re.sub(r"# EMBED_IMPORTS_BEGIN.*?# EMBED_IMPORTS_END", "", source, flags=re.S)
    code = "\n".join((root / path).read_text(encoding="utf-8") for path in
                     ("analysis/workflow_nodes.py", "analysis/generation_nodes.py")) + "\n" + source

    def node(node_id):
        return next(n["data"] for n in graph["nodes"] if n["id"] == node_id)

    def add(node_id, kind, title, **data):
        position = {"x": 1000+len(graph["nodes"])*100, "y": 480}
        graph["nodes"].append({"id": node_id, "type": "custom", "position": position, "positionAbsolute": position,
            "width": 244, "height": 100, "sourcePosition": "right", "targetPosition": "left",
            "data": {"type": kind, "title": title, "desc": "Stage C", "selected": False, **data}})

    def edge(a, b, handle="source"):
        graph["edges"].append({"id": f"{a}-{handle}-{b}", "type": "custom", "source": a, "target": b,
            "sourceHandle": handle, "targetHandle": "target",
            "data": {"sourceType": node(a)["type"], "targetType": node(b)["type"], "isInIteration": False, "isInLoop": False}})

    def code_data(call, variables, payload=False):
        outputs = {key: {"type": "string", "children": None} for key in ("state", "result")}
        if payload: outputs["payload"] = {"type": "string", "children": None}
        else:
            outputs.update({key: {"type": "string", "children": None} for key in ("order_encoded", "batch_encoded")})
        return {"code_language": "python3", "code": code+"\ndef main("+", ".join(variables)+"):\n    return "+call+"\n",
                "variables": [{"variable": key, "value_selector": selector} for key, selector in variables.items()], "outputs": outputs}

    def code_node(key, title, call, variables):
        add(key, "code", title, **code_data(call, variables))

    def branch(key, source, state="continue"):
        add(key, "if-else", "验证通过才继续，否则返回已确认事实与缺失来源", cases=[
            {"case_id": "true", "logical_operator": "and", "conditions": [
                {"id": key+"-condition", "variable_selector": [source, "state"], "comparison_operator": "is", "value": state, "varType": "string"}]}])
        end = key+"_end"
        add(end, "end", "停止联合推断 / 人工确认", outputs=[{"variable": "analysis_result", "value_selector": [source, "result"], "value_type": "string"}])
        edge(source, key); edge(key, end, "false")

    def http(key, path, title):
        # No fail-branch/retry on HTTP: preserve 4xx/5xx bodies in Dify 1.17.1.
        template = json.loads(json.dumps(node("context_http")))
        template.update(title=title, url=base_url.rstrip("/")+path, headers="X-Request-ID:{{#sys.workflow_run_id#}}")
        add(key, "http-request", title, **{k: v for k, v in template.items() if k not in ("type", "title", "desc", "selected")})

    code_node("enterprise_start", "绑定 MES 快照与本次企业请求", "enterprise_begin(previous, context_body, request_id)",
        {"previous": ["compare", "result"], "context_body": ["context_http", "body"], "request_id": ["sys", "workflow_run_id"]})
    branch("enterprise_eligible", "enterprise_start")
    http("links_http", "/api/mes/heats/{{#validate.heat_id_encoded#}}/enterprise-links", "MES 正式任务关联")
    last = "enterprise_start"
    for system, http_id, code_id in (("MES", "links_http", "links_check"), ("ERP", "erp_http", "erp_check"), ("WMS", "wms_http", "wms_check")):
        if system == "ERP": http(http_id, "/api/erp/production-orders/{{#links_check.order_encoded#}}", "ERP 生产订单只读查询")
        if system == "WMS": http(http_id, "/api/wms/batches/{{#links_check.batch_encoded#}}", "WMS 指定批次只读查询")
        code_node(code_id, system+" Schema / 请求 / 摘要 / 身份校验", f"enterprise_accept(previous, {system!r}, status_code, body, request_id)",
            {"previous": [last, "result"], "status_code": [http_id, "status_code"], "body": [http_id, "body"], "request_id": ["sys", "workflow_run_id"]})
        branch(code_id+"_branch", code_id)
        edge(http_id, code_id)
        if system == "MES": edge("enterprise_eligible", http_id, "true")
        elif system == "ERP": edge("links_check_branch", http_id, "true")
        else: edge("erp_check_branch", http_id, "true")
        last = code_id
    code_node("enterprise_joint", "跨系统关联与同单位库存比较", "enterprise_joint(previous)", {"previous": ["wms_check", "result"]})
    edge("wms_check_branch", "enterprise_joint", "true")
    graph["edges"] = [e for e in graph["edges"] if not (e["source"] == "compare" and e["target"] == "anomaly_branch")]
    edge("compare", "enterprise_start"); edge("enterprise_joint", "anomaly_branch")
    node("anomaly_branch")["cases"][0]["conditions"][0]["variable_selector"] = ["enterprise_joint", "state"]
    node("facts_end")["outputs"][0]["value_selector"] = ["enterprise_joint", "result"]
    for key in ("catalog_check", "retrieval_failure"):
        next(v for v in node(key)["variables"] if v["variable"] == "previous")["value_selector"] = ["enterprise_joint", "result"]

    original = {"context_body": ["context_http", "body"], "link_body": ["links_http", "body"],
                "erp_body": ["erp_http", "body"], "wms_body": ["wms_http", "body"], "request_id": ["sys", "workflow_run_id"]}
    node("generation_prepare").update(code_data(
        "enterprise_prepare(previous, retrieval_result, context_body, link_body, erp_body, wms_body, request_id)",
        {"previous": ["evidence", "result"], "retrieval_result": ["retrieval", "result"], **original}, payload=True))
    node("generation_validate").update(code_data(
        "enterprise_validate(previous, retrieval_result, text, structured_output, finish_reason, reasoning_content, context_body, link_body, erp_body, wms_body, request_id)",
        {"previous": ["generation_prepare", "result"], "retrieval_result": ["retrieval", "result"],
         "text": ["deepseek", "text"], "structured_output": ["deepseek", "structured_output"],
         "finish_reason": ["deepseek", "finish_reason"], "reasoning_content": ["deepseek", "reasoning_content"], **original}, payload=True))
    # This validator returns no payload; expose only the two actual output fields.
    node("generation_validate")["outputs"] = {k: v for k, v in node("generation_validate")["outputs"].items() if k in ("state", "result")}
    next(v for v in node("generation_failure")["variables"] if v["variable"] == "previous")["value_selector"] = ["generation_prepare", "result"]
    llm = node("deepseek")
    llm["structured_output"]["schema"] = ENTERPRISE_MODEL_SCHEMA
    llm["prompt_template"][0]["text"] = ("你是受约束的企业报告组织节点，只返回一个符合 schema 的 JSON。输入含 mes_report 和 enterprise_summary。"
        "mes_report 是已经验证的完整报告，整个对象逐字复制，不调整其列表、不重新撰写 answer。answer 字符串中的每一个换行符必须保持，不能换成空格。"
        "只允许调整 enterprise_summary 列表内部顺序，全部 claim_id 和 text 必须逐字保留。"
        "enterprise_summary 只能保留原 claim_id/text；不能发明订单、库存、批次、API 来源、工艺结论或设备动作。API 事实不是文档 citation。"
        "引用只来自给定 mes_report.citations，所有 metadata/hash 不变。不要 think、Markdown 或 JSON 之外的文本。")
    dsl["app"]["description"] = "Stage C：MES/ERP/WMS 只读事实 → 身份与 provenance → Qwen/evidence → DeepSeek → A/B/C 独立校验；人工复核。"
    return dsl


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--base-url", default="http://host.docker.internal:18089")
    parser.add_argument("--source-registry", type=Path, default=Path("assets/analysis_demo/dify_source_registry.json"))
    parser.add_argument("--output", type=Path, default=Path("workflows/heat_analysis.stage_c.yml"))
    args = parser.parse_args()
    args.output.write_text(json.dumps(build_enterprise_workflow(args.dataset_id, args.base_url,
        json.loads(args.source_registry.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
