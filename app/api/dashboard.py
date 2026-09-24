"""GET /dashboard — simple HTML patient browser (no separate frontend deploy)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings

router = APIRouter(tags=["dashboard"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Serve the intake dashboard. Data is loaded client-side from /patients."""
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "clinic_name": settings.clinic_name,
        },
    )
