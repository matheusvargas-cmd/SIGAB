"""Página exibida quando o gabinete do usuário está com a assinatura/
trial vencidos (ver GabineteVencido, app/core/contexto.py). Depende só de
obter_usuario_atual — nunca de obter_contexto_atual/exigir_perfil: esta
página É o destino do redirecionamento quando a checagem de validade
falha, então repetir aquela checagem aqui causaria um loop de redirect.
O gabinete_id é lido direto da sessão só para exibir nome/plano/vencimento
— sem revalidar vínculo/validade, que não é o propósito desta tela."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import obter_usuario_atual
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.gabinete_service import GabineteService

router = APIRouter(tags=["Assinatura"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/assinatura", response_class=HTMLResponse)
def vencido(
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    # SUPERADMIN nunca é bloqueado por validade (requisito 10) — se por
    # algum motivo alguém trouxer esta URL manualmente para uma sessão de
    # SUPERADMIN, o destino correto é o painel global, nunca esta tela.
    if usuario.super_admin:
        return RedirectResponse("/superadmin/gabinetes", status_code=303)

    gabinete_id = request.session.get("gabinete_id")
    gabinete = GabineteService.obter_por_id(db, gabinete_id) if gabinete_id else None

    return templates.TemplateResponse(
        request=request,
        name="assinatura/vencido.html",
        context={
            "titulo": "Assinatura",
            "usuario_nome": usuario.nome,
            "gabinete": gabinete,
        },
    )
