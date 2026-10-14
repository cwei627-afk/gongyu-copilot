"""Local PoC BFF + static product UI; no credentials in client configuration."""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.copilot.contracts import Query, ProductResponse
from app.copilot.gateway import Gateway
from app.copilot.router import route
from app.copilot.transport import ServiceFailure


def create_gateway(gateway=None, static_dir=None):
    service = gateway or Gateway()
    application = FastAPI(title='制造业AI Copilot · 产品入口', version='1.0')
    application.state.gateway = service

    @application.middleware('http')
    async def boundaries(request: Request, call_next):
        if request.method == 'POST' and request.url.path in ('/api/copilot/query', '/api/workspace/query'):
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse(status_code=403, content={'message': '请求来源不匹配'})
            try:
                if int(request.headers.get('content-length', '0')) > 16000:
                    return JSONResponse(status_code=413, content={'message': '问题过长'})
            except ValueError:
                return JSONResponse(status_code=400, content={'message': '请求格式有误'})
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @application.post('/api/copilot/query', response_model=ProductResponse)
    def query(body: Query):
        return service.query(body)

    @application.post('/api/workspace/query')
    def workspace_query(body: Query):
        from app.copilot.workspace import query as workspace_query
        return workspace_query(service, body)

    @application.get('/api/workspace/health')
    def workspace_health():
        from app.copilot.workspace import health
        return health(service)

    @application.get('/api/workspace/demo-info')
    def workspace_info():
        try:
            from app.copilot.workspace import overview
            return overview(service)
        except (ServiceFailure, ValueError, KeyError):
            return JSONResponse(status_code=503, content={'message': '演示数据说明暂时不可用'})

    @application.get('/api/copilot/health')
    def health():
        try:
            source = service.transport.source('/health')
            if source['status'] != 'ok':
                raise ServiceFailure()
            return {'status': 'ok', 'gateway': 'ok', 'source': 'ok', 'router': 'ok'}
        except (ServiceFailure, KeyError):
            return JSONResponse(status_code=503, content={'status': 'unavailable', 'gateway': 'ok', 'source': 'unavailable', 'router': 'ok'})

    @application.get('/api/copilot/router-health')
    def router_health():
        valid = route('修改PLC').intent.value == 'UNSUPPORTED' and route('查询当前生产状态').intent.value == 'CLARIFICATION'
        return {'status': 'ok' if valid else 'unavailable'}

    @application.get('/api/copilot/demo-info')
    def demo_info():
        try:
            return service.overview()
        except (ServiceFailure, ValueError, KeyError):
            return JSONResponse(status_code=503, content={'message': '演示数据说明暂时不可用'})

    folder = Path(static_dir) if static_dir else Path(__file__).resolve().parents[2] / 'frontend/dist'
    if folder.is_dir():
        application.mount('/', StaticFiles(directory=folder, html=True), name='product')
    return application


app = create_gateway()
