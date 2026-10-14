"""Normalize Dify workflow_finished.data at the calling boundary, without an LLM.

HTTP transport or Code sandbox failure has no successful End output in Dify 1.17.1.
Treat that as a system failure; never manufacture an absent heat or process result.
"""
import json

from app.analysis.workflow_nodes import begin, stop


def normalize_finished(data, heat_id, analysis_request):
    if isinstance(data, dict) and data.get("status") in ("succeeded", "partial-succeeded"):
        try:
            result = json.loads(data["outputs"]["analysis_result"])
            if (isinstance(result, dict) and result.get("heat_id") == heat_id
                    and result.get("status") in ("request_error", "data_error", "system_error",
                                                 "no_anomaly", "abstain", "review_required")):
                return result
        except (KeyError, TypeError, ValueError):
            pass
    initial = json.loads(begin(heat_id, analysis_request)["result"])
    return json.loads(stop(initial, "system", "WORKFLOW_EXECUTION_FAILED",
                           "Dify 执行未成功返回有效业务结果；事实状态未知，请人工确认。")["result"])
