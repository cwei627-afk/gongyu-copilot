"""Fixed server-side destinations; never accept a URL or credentials from a user."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from app.analysis.generation_nodes import strict_json

ROOT = Path(__file__).resolve().parents[2]


class ServiceFailure(Exception):
    def __init__(self, code='SERVICE_UNAVAILABLE', metadata=None):
        self.code = code
        self.metadata = metadata or {}
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def config():
    values = {}
    for path in (ROOT / '.env.demo.local', ROOT / '.env.stage-f.local'):
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1); values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith(('DIFY_', 'COPILOT_'))})
    return values


def http(url, payload=None, key=None, timeout=240):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        raise ServiceFailure('INVALID_SERVER_CONFIGURATION')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    request = Request(url, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None, headers=headers)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(4_000_001)
            if len(body) > 4_000_000:
                raise ServiceFailure('INVALID_SERVICE_RESPONSE')
            return strict_json(body.decode('utf-8'))
    except HTTPError as exc:
        raise ServiceFailure('SERVICE_HTTP_' + str(exc.code)) from None
    except (TimeoutError, OSError):
        raise ServiceFailure('SERVICE_TIMEOUT_OR_CONNECTION_FAILED') from None
    except (ValueError, UnicodeError):
        raise ServiceFailure('INVALID_SERVICE_RESPONSE') from None


class Transport:
    def __init__(self, values=None):
        self.values = values if values is not None else config()

    def workflow(self, kind, inputs):
        key = self.values.get('DIFY_' + kind + '_API_KEY')
        if not key:
            raise ServiceFailure('SERVICE_NOT_CONFIGURED')
        base = self.values.get('DIFY_BASE_URL', 'http://localhost').rstrip('/')
        packet = http(base + '/v1/workflows/run', {'inputs': inputs, 'response_mode': 'blocking', 'user': 'unified-copilot'}, key)
        try:
            data = packet['data']
            if data['status'] != 'succeeded':
                raise ServiceFailure('WORKFLOW_EXECUTION_FAILED', {
                    'workflow_run_id': data.get('id'), 'workflow_id': data.get('workflow_id'), 'engine': kind})
            field = {'C': 'analysis_result', 'D': 'query_result', 'E1': 'qa_result', 'F_INTERNAL': 'qa_result', 'F_PUBLIC': 'qa_result', 'F_ROUTER': 'route_result'}[kind]
            result = strict_json(data['outputs'][field])
            if not isinstance(result, dict) or (kind != 'F_ROUTER' and result.get('automatic_actions') != []):
                raise ValueError('invalid read-only contract')
            return result, {'workflow_run_id': data['id'], 'workflow_id': data['workflow_id'], 'engine': kind}
        except (KeyError, TypeError, ValueError):
            raise ServiceFailure('INVALID_WORKFLOW_RESULT') from None

    def source(self, path, params=None):
        if path not in ('/api/mes/heats', '/api/erp/production-orders', '/api/wms/inventory', '/api/demo/summary', '/health'):
            raise ServiceFailure('SOURCE_OPERATION_NOT_ALLOWED')
        base = self.values.get('COPILOT_SOURCE_BASE', 'http://127.0.0.1:18090').rstrip('/')
        query = '?' + urlencode(params) if params else ''
        return http(base + path + query, timeout=15)
