"""Separate Stage D entry point; original app.main and its OpenAPI are unchanged."""
import hmac
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from app.main import create_app
from app.readonly_agent.gateway import Gateway, GateError, failure


class Begin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str
    request_id: str


class Finish(BaseModel):
    model_config = ConfigDict(extra='forbid')
    capability: str
    text: str
    execution_failed: bool = False


class Trace(BaseModel):
    model_config = ConfigDict(extra='forbid')
    capability: str


def create_agent_app(data_dir=None, gateway=None, control_secret=None):
    app = create_app(data_dir)
    gateway = gateway or Gateway(os.environ.get('AGENT_BACKEND_BASE', 'http://127.0.0.1:8000'))
    secret = control_secret or os.environ.get('AGENT_CONTROL_SECRET', '')
    app.state.agent_gateway = gateway

    def control(request):
        if not secret or not hmac.compare_digest(request.headers.get('X-Agent-Control', ''), secret):
            raise GateError('CONTROL_NOT_AUTHORIZED')

    @app.exception_handler(GateError)
    async def handle_gate(request, exc):
        return JSONResponse(status_code=403 if 'AUTHORIZED' in exc.code else 409,
                            content=failure(exc.code, exc.category))

    @app.post('/agent/control/begin', include_in_schema=False)
    def begin(body: Begin, request: Request):
        control(request)
        try:
            return {'state': 'agent', **gateway.begin(body.query, body.request_id)}
        except GateError as exc:
            return {'state': 'stop', 'result': failure(exc.code, exc.category), 'capability': '', 'permission': {}}

    @app.post('/agent/control/finish', include_in_schema=False)
    def finish(body: Finish, request: Request):
        control(request)
        if body.execution_failed:
            run = gateway._run(body.capability)
            with run.lock:
                if not run.error:
                    run.error = failure('AGENT_EXECUTION_FAILED', 'system')
        return gateway.finish(body.capability, body.text)

    @app.get('/agent/tools/{operation}/{entity_id}', include_in_schema=False)
    def tool(operation: str, entity_id: str, capability: str):
        return gateway.call(capability, operation, entity_id)

    @app.post('/agent/control/trace', include_in_schema=False)
    def trace(body: Trace, request: Request):
        control(request)
        run = gateway.runs.get(body.capability)
        if not run: raise GateError('INVALID_CAPABILITY')
        with run.lock:
            return {'request_id': run.request_id, 'permission': run.permission,
                    'calls': run.calls, 'data_sources': run.sources, 'consumed': run.consumed}

    return app


app = create_agent_app()
