"""One server-side gateway around the existing published business capabilities."""
import json
import re
import threading
from pathlib import Path
from uuid import uuid4
from app.copilot.contracts import Intent, Query
from app.copilot.context import Context
from app.copilot.router import route, classify_output
from app.copilot.transport import Transport, ServiceFailure
from app.copilot import presenter
from app.knowledge_qa.nodes import QA_ALIASES, qa_normalize


class Gateway:
    def __init__(self, transport=None, context=None, router=None):
        self.transport = transport or Transport()
        self.context = context or Context()
        self.route = router or route
        self.slots = threading.BoundedSemaphore(4)

    def query(self, query: Query):
        request_id = str(uuid4())
        references = self.context.verify(query.context_token)
        kind = 'order' if re.search(r'这个订单|该订单', query.question) else 'batch' if re.search(r'这个批次|该批次', query.question) else 'order' if '对应物料' in query.question and 'order' in references else 'heat'
        context = {'entity_kind': kind, 'entity_id': references[kind]} if kind in references else None
        selected = self.route(query.question, verified_context=context)
        if selected.intent == Intent.UNSUPPORTED:
            return presenter.stop(request_id, selected, 'unsupported', selected.reason)
        if selected.intent == Intent.CLARIFICATION:
            # Optional published classifier only assigns a closed intent. No IDs or answers.
            if selected.reason == 'UNCERTAIN_INTENT':
                try:
                    classified, _ = self.transport.workflow('F_ROUTER', {'question': query.question})
                    intent = classify_output(json.dumps(classified))
                    if intent in (Intent.INTERNAL_KNOWLEDGE, Intent.GENERAL_INDUSTRY_KNOWLEDGE):
                        selected.intent = intent
                except (ServiceFailure, ValueError, TypeError):
                    pass
            if selected.intent == Intent.CLARIFICATION:
                return presenter.stop(request_id, selected, 'clarification', selected.reason)
        if not self.slots.acquire(blocking=False):
            return presenter.stop(request_id, selected, 'system_error', 'GATEWAY_BUSY')
        try:
            if selected.collection:
                path = {'mes': '/api/mes/heats', 'erp': '/api/erp/production-orders', 'wms': '/api/wms/inventory'}[selected.collection]
                return presenter.collection(request_id, selected, self.transport.source(path, selected.filters))
            if selected.intent == Intent.ANOMALY_ANALYSIS:
                raw, meta = self.transport.workflow('C', {'heat_id': selected.entity_id, 'analysis_request': 'all'})
            elif selected.intent == Intent.LIVE_ENTERPRISE_QUERY:
                raw, meta = self.transport.workflow('D', {'query': selected.canonical_query})
            elif selected.intent == Intent.GENERAL_INDUSTRY_KNOWLEDGE:
                raw, meta = self.transport.workflow('F_PUBLIC', {'question': query.question})
            else:
                original = any(qa_normalize(query.question) == qa_normalize(alias) for aliases in QA_ALIASES.values() for alias in aliases)
                raw, meta = self.transport.workflow('E1' if original else 'F_INTERNAL', {'question': query.question})
            output = presenter.result(request_id, selected, raw, meta)
            if raw['status'] == 'verified_read_only':
                entities = {}
                for operation, fact in raw['facts'].items():
                    for name, field in [('heat', 'heat_id'), ('order', 'production_order_id'), ('batch', 'batch_id')]:
                        if field in fact and operation in ('mes_heat', 'mes_links', 'erp_order', 'wms_batch'):
                            entities[name] = fact[field]
                output.context_token = self.context.issue(entities)
            return output
        except ServiceFailure as exc:
            return presenter.stop(request_id, selected, 'system_error', exc.code, exc.metadata)
        except (ValueError, KeyError, TypeError, AttributeError):
            return presenter.stop(request_id, selected, 'system_error', 'UNVERIFIED_SERVICE_RESULT')
        finally:
            self.slots.release()

    def overview(self):
        data = self.transport.source('/api/demo/summary')
        if data.get('fictional') is not True:
            raise ServiceFailure('INVALID_SOURCE_SUMMARY')
        root = Path(__file__).resolve().parents[2]
        internal = json.loads((root / 'assets/copilot_knowledge/corpus.json').read_text(encoding='utf-8'))
        public = json.loads((root / 'assets/public_reference/corpus.json').read_text(encoding='utf-8'))
        return {**data, 'internal_document_count': len(internal['documents']),
                'internal_current_document_count': sum(d['status'] == 'active' for d in internal['documents']),
                'public_reference_count': len(public['documents']),
                'notice': '所有生产数据和企业规程均为虚构演示资料。公开行业参考与企业制度严格区分。'}
