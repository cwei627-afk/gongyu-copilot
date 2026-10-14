"""Add Stage B after the frozen Stage A graph; leave its implementation intact."""
import argparse
import json
from pathlib import Path

from app.analysis.export_workflow import build_workflow
from app.analysis.generation_nodes import GENERATION_SCHEMA


def build_generation_workflow(dataset_id, base_url, source_registry):
    dsl = build_workflow(dataset_id, base_url, source_registry)
    graph = dsl["workflow"]["graph"]
    code = Path(__file__).with_name("generation_nodes.py").read_text(encoding="utf-8")

    def add(node_id, kind, title, x, y, **data):
        graph["nodes"].append({"id": node_id, "type": "custom", "position": {"x": x, "y": y},
                               "positionAbsolute": {"x": x, "y": y}, "width": 244, "height": 100,
                               "sourcePosition": "right", "targetPosition": "left",
                               "data": {"type": kind, "title": title, "desc": "Stage B", "selected": False, **data}})

    def edge(a, b, handle="source"):
        types = {node["id"]: node["data"]["type"] for node in graph["nodes"]}
        graph["edges"].append({"id": f"{a}-{handle}-{b}", "type": "custom", "source": a, "target": b,
                               "sourceHandle": handle, "targetHandle": "target",
                               "data": {"sourceType": types[a], "targetType": types[b], "isInIteration": False, "isInLoop": False}})

    def code_node(node_id, title, call, variables, x, y, payload=False):
        outputs = {"state": {"type": "string", "children": None}, "result": {"type": "string", "children": None}}
        if payload: outputs["payload"] = {"type": "string", "children": None}
        add(node_id, "code", title, x, y, code_language="python3",
            code=code+"\ndef main("+", ".join(variables)+"):\n    return "+call+"\n",
            variables=[{"variable": key, "value_selector": value} for key, value in variables.items()], outputs=outputs)

    code_node("generation_prepare", "仅已验证 evidence 可进入生成", "prepare_generation(previous, retrieval_result, request_id)",
              {"previous": ["evidence", "result"], "retrieval_result": ["retrieval", "result"],
               "request_id": ["sys", "workflow_run_id"]}, 4500, 0, payload=True)
    add("generation_branch", "if-else", "证据不足不得调用 LLM", 4800, 0,
        cases=[{"case_id": "true", "logical_operator": "and", "conditions": [
            {"id": "generate-only", "variable_selector": ["generation_prepare", "state"],
             "comparison_operator": "is", "value": "generate", "varType": "string"}]}])
    add("deepseek", "llm", "DeepSeek：受约束的事实/规程报告组织", 5100, 0,
        model={"provider": "langgenius/deepseek/deepseek", "name": "deepseek-flash", "mode": "chat",
               "completion_params": {"thinking": False, "temperature": 0.1, "max_tokens": 8192, "response_format": "json_object"}},
        prompt_template=[
            {"role": "system", "text": "你是制造业辅助分析报告整理节点。输入仅来自已验证 MES 事实、有效规则和 SOP 原文检查项。输出一个 JSON 对象，严格遵守 schema。保留全部 summary/check/citation 项及原文；允许调整 summary 或 check 列表内部顺序，answer 必须按新的列表顺序以换行连接 summary.text、check.text 加空格加 [cite:citation_id]、最后 human_confirmation。不得增加句子、工艺参数或设备动作，不得修改事实/文本/ID/metadata/hash，不得引用输入之外的来源，不输出 think 或 Markdown。生产处置需要人工确认。"},
            {"role": "user", "text": "整理以下已通过 Evidence First 的本次请求报告。只返回 JSON：\n{{#generation_prepare.payload#}}"}],
        context={"enabled": False, "variable_selector": []}, vision={"enabled": False},
        structured_output_enabled=True, structured_output={"schema": GENERATION_SCHEMA}, reasoning_format="separated",
        error_strategy="fail-branch", retry_config={"retry_enabled": False, "max_retries": 0, "retry_interval": 100})
    code_node("generation_validate", "JSON schema + Citation coverage + 正文支持范围",
              "validate_generation(previous, retrieval_result, text, structured_output, finish_reason, reasoning_content, request_id)",
              {"previous": ["evidence", "result"], "retrieval_result": ["retrieval", "result"],
               "text": ["deepseek", "text"], "structured_output": ["deepseek", "structured_output"],
               "finish_reason": ["deepseek", "finish_reason"], "reasoning_content": ["deepseek", "reasoning_content"],
               "request_id": ["sys", "workflow_run_id"]}, 5400, 0)
    code_node("generation_failure", "Provider/API 失败：停止生成与引用", "generation_failure(previous)",
              {"previous": ["evidence", "result"]}, 5400, 240)
    for node_id, source, y in (("generation_end", "generation_validate", 0), ("generation_failure_end", "generation_failure", 240)):
        add(node_id, "end", "输出受验证结构化结果", 5700, y,
            outputs=[{"variable": "analysis_result", "value_selector": [source, "result"], "value_type": "string"}])
    graph["edges"] = [item for item in graph["edges"] if not (item["source"] == "evidence" and item["target"] == "report_end")]
    stopped = next(node for node in graph["nodes"] if node["id"] == "report_end")
    stopped["data"]["outputs"][0]["value_selector"] = ["generation_prepare", "result"]
    stopped["position"] = stopped["positionAbsolute"] = {"x": 4800, "y": 240}
    for a, b, handle in (("evidence", "generation_prepare", "source"), ("generation_prepare", "generation_branch", "source"),
                         ("generation_branch", "report_end", "false"), ("generation_branch", "deepseek", "true"),
                         ("deepseek", "generation_validate", "source"), ("deepseek", "generation_failure", "fail-branch"),
                         ("generation_validate", "generation_end", "source"), ("generation_failure", "generation_failure_end", "source")):
        edge(a, b, handle)
    dsl["app"]["description"] = "Stage B：MES/规则 → 受控 evidence → DeepSeek → schema/citation/正文校验；人工复核。完全虚构 PoC。"
    return dsl


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--base-url", default="http://host.docker.internal:18088")
    parser.add_argument("--source-registry", type=Path, default=Path("assets/analysis_demo/dify_source_registry.json"))
    parser.add_argument("--output", type=Path, default=Path("workflows/heat_analysis.stage_b.yml"))
    args = parser.parse_args()
    registry = json.loads(args.source_registry.read_text(encoding="utf-8"))
    dsl = build_generation_workflow(args.dataset_id, args.base_url, registry)
    args.output.write_text(json.dumps(dsl, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
