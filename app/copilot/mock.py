"""Compose-compatible Mock adapters; do not alter original app factories or schemas."""
from app.main import create_app
from app.readonly_agent.main import create_agent_app
from app.demo_dataset.api import router
from app.demo_dataset.display_ids import router as display_router

app_c = create_app()
app_c.include_router(router)
app_c.include_router(display_router)
app_d = create_agent_app()
app_d.include_router(router)
app_d.include_router(display_router)
