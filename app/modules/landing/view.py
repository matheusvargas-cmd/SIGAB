"""Landing page comercial pública do Gabinete 360 — renderizada na raiz
(`/`) apenas para quem não tem sessão autenticada (ver
app/modules/dashboard/controller.py:dashboard). Isolada de propósito:
nenhum dado de gabinete/eleitor/demanda, nenhuma consulta ao banco, nada
que dependa de ContextoSessao. Template e CSS/JS próprios, sem tocar em
shared/base.html nem em style.css do sistema interno."""

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import TEMPLATES_DIR

_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def renderizar_landing(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request=request, name="landing/index.html", context={})
