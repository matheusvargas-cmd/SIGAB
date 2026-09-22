"""Página exibida quando o gabinete do usuário está com a assinatura/
trial vencidos (ver GabineteVencido, app/core/contexto.py), o checkout de
contratação/renovação (Fase 2 — Asaas) e as páginas de retorno do
Checkout (successUrl/cancelUrl/expiredUrl).

Nenhuma rota deste módulo depende de obter_contexto_atual/exigir_perfil:
todas são destino ou origem do fluxo de assinatura vencida, então
repetir aquela checagem aqui causaria um loop de redirecionamento. O
vínculo usuário↔gabinete é sempre revalidado explicitamente via
app.core.contexto.obter_gabinete_vinculado (mesma condição de
obter_contexto_atual, sem a parte de ativo/validade) — nunca se confia
em gabinete_id de sessão sem essa revalidação, e nunca se aceita
gabinete_id vindo do cliente (formulário/query string)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR, settings
from app.core.contexto import obter_gabinete_vinculado, obter_usuario_atual
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.asaas_service import AsaasError, AsaasNaoConfiguradoError, AsaasService
from app.services.assinatura_service import PLANOS, montar_external_reference

router = APIRouter(tags=["Assinatura"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _url_absoluta(request: Request, caminho: str) -> str:
    return str(request.base_url).rstrip("/") + caminho


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
    gabinete = obter_gabinete_vinculado(db, usuario.id, gabinete_id)
    if gabinete_id and gabinete is None:
        # Vínculo removido depois que a sessão foi aberta — gabinete_id
        # obsoleto é descartado; a navegação seguinte (recarregar, "Sair")
        # segue o fluxo normal de contexto inválido já existente.
        request.session.pop("gabinete_id", None)

    return templates.TemplateResponse(
        request=request,
        name="assinatura/vencido.html",
        context={
            "titulo": "Assinatura",
            "usuario_nome": usuario.nome,
            "gabinete": gabinete,
            "asaas_sandbox": settings.asaas_ambiente == "sandbox",
            "asaas_disponivel": settings.asaas_configurado,
            "erro": None,
        },
    )


@router.post("/assinatura/checkout", response_class=HTMLResponse)
def iniciar_checkout(
    request: Request,
    plano: str = Form(...),
    cpf_cnpj: str = Form(...),
    nome: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(obter_usuario_atual),
):
    """Inicia a contratação/renovação — cria (ou reaproveita) o cliente no
    Asaas e um Checkout, e redireciona o navegador para a URL hospedada
    pelo Asaas. NUNCA ativa a assinatura aqui: criar um Checkout não é
    pagamento confirmado — isso só acontece via POST /webhooks/asaas."""
    # SUPERADMIN não contrata assinatura de gabinete pela sessão normal
    # (ele nunca "está usando" um gabinete — não tem MembroGabinete).
    if usuario.super_admin:
        return RedirectResponse("/superadmin/gabinetes", status_code=303)

    # gabinete_id vem exclusivamente da sessão (nunca de Form/query string
    # — impossível o cliente escolher outro gabinete) e é revalidado contra
    # o vínculo atual do usuário, exatamente como obter_contexto_atual.
    gabinete_id = request.session.get("gabinete_id")
    gabinete = obter_gabinete_vinculado(db, usuario.id, gabinete_id)
    if gabinete is None:
        request.session.pop("gabinete_id", None)
        return RedirectResponse("/selecionar-gabinete", status_code=303)

    def _erro(mensagem: str, status_code: int = 400):
        return templates.TemplateResponse(
            request=request,
            name="assinatura/vencido.html",
            context={
                "titulo": "Assinatura",
                "usuario_nome": usuario.nome,
                "gabinete": gabinete,
                "asaas_sandbox": settings.asaas_ambiente == "sandbox",
                "asaas_disponivel": settings.asaas_configurado,
                "erro": mensagem,
            },
            status_code=status_code,
        )

    if plano not in PLANOS:
        return _erro("Plano inválido.")

    if not settings.asaas_configurado:
        return _erro("Pagamentos ainda não estão configurados neste ambiente.", status_code=503)

    cpf_cnpj_normalizado = "".join(caractere for caractere in cpf_cnpj if caractere.isdigit())
    if len(cpf_cnpj_normalizado) not in (11, 14):
        return _erro("Informe um CPF ou CNPJ válido (somente números, 11 ou 14 dígitos).")

    nome_normalizado = (nome or "").strip() or gabinete.responsavel or gabinete.nome
    external_reference = montar_external_reference(gabinete.id, plano)

    try:
        cliente_id = AsaasService.obter_ou_criar_cliente(
            external_reference=external_reference,
            nome=nome_normalizado,
            cpf_cnpj=cpf_cnpj_normalizado,
            email=gabinete.email_institucional or None,
        )
        if gabinete.asaas_customer_id != cliente_id:
            gabinete.asaas_customer_id = cliente_id
            db.commit()

        checkout = AsaasService.criar_checkout(
            customer_id=cliente_id,
            descricao=PLANOS[plano]["descricao"],
            valor=PLANOS[plano]["valor"],
            ciclo=PLANOS[plano]["ciclo"],
            external_reference=external_reference,
            success_url=_url_absoluta(request, "/assinatura/sucesso"),
            cancel_url=_url_absoluta(request, "/assinatura/cancelado"),
            expired_url=_url_absoluta(request, "/assinatura/expirado"),
        )
    except AsaasNaoConfiguradoError:
        return _erro("Pagamentos ainda não estão configurados neste ambiente.", status_code=503)
    except AsaasError:
        return _erro("Não foi possível iniciar o checkout agora. Tente novamente em alguns minutos.", 502)

    checkout_id = checkout.get("id")
    if checkout_id:
        gabinete.asaas_checkout_id = checkout_id
        db.commit()

    link_checkout = checkout.get("link") or checkout.get("invoiceUrl") or checkout.get("url")
    if not link_checkout:
        return _erro("O Asaas não retornou o link do checkout. Tente novamente.", 502)

    return RedirectResponse(link_checkout, status_code=303)


def _pagina_callback(
    request: Request, db: Session, usuario: Usuario, nome_template: str, titulo: str
) -> HTMLResponse:
    gabinete_id = request.session.get("gabinete_id")
    # obter_gabinete_vinculado nunca retorna dado de gabinete ao qual o
    # usuário não pertence mais — coerente com a correção já aplicada em
    # vencido() (Fase 1, auditoria item 10.2). Para SUPERADMIN (nunca tem
    # gabinete_id/MembroGabinete) isso já resolve None naturalmente.
    gabinete = obter_gabinete_vinculado(db, usuario.id, gabinete_id)

    return templates.TemplateResponse(
        request=request,
        name=f"assinatura/{nome_template}.html",
        context={"titulo": titulo, "usuario_nome": usuario.nome, "gabinete": gabinete},
    )


@router.get("/assinatura/sucesso", response_class=HTMLResponse)
def checkout_sucesso(
    request: Request, db: Session = Depends(get_db), usuario: Usuario = Depends(obter_usuario_atual)
):
    """Retorno de successUrl — só confirma que o pagador voltou do
    Checkout. NUNCA libera a assinatura aqui: a liberação é exclusiva do
    Webhook (POST /webhooks/asaas), que pode inclusive já ter processado
    o pagamento antes deste retorno acontecer, ou ainda estar a caminho."""
    return _pagina_callback(request, db, usuario, "sucesso", "Pagamento recebido")


@router.get("/assinatura/cancelado", response_class=HTMLResponse)
def checkout_cancelado(
    request: Request, db: Session = Depends(get_db), usuario: Usuario = Depends(obter_usuario_atual)
):
    return _pagina_callback(request, db, usuario, "cancelado", "Checkout cancelado")


@router.get("/assinatura/expirado", response_class=HTMLResponse)
def checkout_expirado(
    request: Request, db: Session = Depends(get_db), usuario: Usuario = Depends(obter_usuario_atual)
):
    return _pagina_callback(request, db, usuario, "expirado", "Checkout expirado")
