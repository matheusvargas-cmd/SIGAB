"""Página exibida quando o gabinete do usuário está com a assinatura/
trial vencidos (ver GabineteVencido, app/core/contexto.py). Depende só de
obter_usuario_atual — nunca de obter_contexto_atual/exigir_perfil: esta
página É o destino do redirecionamento quando a checagem de validade
falha, então repetir aquela checagem aqui causaria um loop de redirect.
O gabinete_id é lido direto da sessão, mas o vínculo com o usuário atual
é revalidado explicitamente (mesma condição de obter_contexto_atual,
sem a parte de ativo/validade — ver vencido() abaixo) antes de exibir
qualquer nome/plano/vencimento: uma sessão antiga não pode continuar
mostrando dados de um gabinete do qual o usuário já não é mais membro."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import obter_usuario_atual
from app.core.database import get_db
from app.models.membro_gabinete import MembroGabinete
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
    gabinete = None
    if gabinete_id:
        # Mesma checagem de vínculo de obter_contexto_atual — nunca a
        # checagem de ativo/validade também, que redirecionaria de volta
        # para esta própria página e criaria um loop. Sem vínculo válido
        # (removido depois que a sessão foi aberta, por exemplo), trata
        # como contexto inválido: nenhum nome/plano/vencimento é exibido,
        # e o gabinete_id obsoleto é removido da sessão — a navegação
        # seguinte (recarregar, ou "Sair") segue o fluxo normal de
        # contexto inválido já existente (GabineteNaoSelecionado).
        membro = db.scalar(
            select(MembroGabinete).where(
                MembroGabinete.usuario_id == usuario.id,
                MembroGabinete.gabinete_id == gabinete_id,
                MembroGabinete.ativo.is_(True),
            )
        )
        if membro is None:
            request.session.pop("gabinete_id", None)
        else:
            gabinete = GabineteService.obter_por_id(db, gabinete_id)

    return templates.TemplateResponse(
        request=request,
        name="assinatura/vencido.html",
        context={
            "titulo": "Assinatura",
            "usuario_nome": usuario.nome,
            "gabinete": gabinete,
        },
    )
