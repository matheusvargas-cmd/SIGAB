import json
import logging
import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.models.demanda import Demanda
from app.models.gabinete import Gabinete
from app.services.atendimento_publico_service import (
    AtendimentoPublicoService,
    SolicitacaoEmProcessamentoError,
)
from app.services.categoria_service import CategoriaService
from app.services.eleitor_service import EleitorService
from app.services.gabinete_service import GabineteService
from app.services.subcategoria_service import SubcategoriaService

logger = logging.getLogger(__name__)

# Limitador simples (em memória, por processo) da busca de eleitor por
# CPF no formulário público — sem login, então sem como confirmar que
# quem digitou o CPF é o dono dele. Não elimina o risco de alguém tentar
# descobrir se um CPF específico está cadastrado, só dificulta uma
# varredura em massa. Chave por (IP, public_token): o mesmo IP não fica
# bloqueado para um gabinete só porque esgotou o limite testando outro.
# Em memória de propósito (sem Redis/banco) — reinicia a cada deploy, e
# só vale para um único processo; aceitável na escala deste sistema, mesmo
# trade-off já assumido em outros pontos simples do projeto (ex.:
# app.state.ultimo_heartbeat em main.py).
_TENTATIVAS_BUSCA_CPF: dict[tuple[str, str], list[float]] = defaultdict(list)
_JANELA_LIMITE_SEGUNDOS = 600
_LIMITE_TENTATIVAS = 15


def _limite_busca_cpf_excedido(chave: tuple[str, str]) -> bool:
    agora = time.monotonic()
    tentativas = _TENTATIVAS_BUSCA_CPF[chave]
    tentativas[:] = [instante for instante in tentativas if agora - instante < _JANELA_LIMITE_SEGUNDOS]
    if len(tentativas) >= _LIMITE_TENTATIVAS:
        return True
    tentativas.append(agora)
    return False

# Prefixo próprio /cidadao, fora de /eleitor, /eleitores, /demandas — nunca
# reaproveitado por essas rotas autenticadas de propósito: é uma porta de
# entrada completamente diferente (sem login, sem ContextoSessao). O
# gabinete nunca é lido de sessão/cookie/parâmetro solto — só do
# public_token no path, resolvido uma vez por requisição via
# GabineteService.obter_por_public_token.
router = APIRouter(prefix="/cidadao", tags=["Atendimento ao Cidadão"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

COOKIE_PROTOCOLO = "sigab_protocolo_cidadao"


def _chave_sessao_csrf(public_token: str) -> str:
    # Uma chave por public_token (não uma única "cidadao_csrf" global) só
    # para não gerar um falso-positivo de "CSRF inválido" se a mesma
    # pessoa tiver duas abas abertas em formulários de gabinetes
    # diferentes — nunca um requisito de segurança, só evita um
    # incômodo. A mesma sessão (cookie assinado do SessionMiddleware, já
    # existente para o login) é reaproveitada; nenhuma configuração nova.
    return f"cidadao_csrf_{public_token}"


def _gerar_e_guardar_csrf(request: Request, public_token: str) -> str:
    token = secrets.token_urlsafe(32)
    request.session[_chave_sessao_csrf(public_token)] = token
    return token


def _csrf_valido(request: Request, public_token: str, token_recebido: str) -> bool:
    token_esperado = request.session.get(_chave_sessao_csrf(public_token))
    if not token_esperado or not token_recebido:
        return False
    return secrets.compare_digest(token_esperado, token_recebido)


def _resolver_gabinete_ativo(db: Session, public_token: str) -> Gabinete | None:
    """None tanto para token inexistente quanto para gabinete inativo — de
    propósito, a mesma resposta (página "link indisponível") para os dois
    casos, para não deixar alguém varrendo tokens descobrir se um token
    "existe mas está desativado" vs "nunca existiu"."""
    gabinete = GabineteService.obter_por_public_token(db, public_token)
    if gabinete is None or not gabinete.ativo:
        return None
    return gabinete


def _pagina_indisponivel(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="cidadao/indisponivel.html",
        context={"titulo": "Link indisponível"},
        status_code=404,
    )


@router.get("/{public_token}/eleitor-por-cpf")
def eleitor_por_cpf(request: Request, public_token: str, cpf: str = "", db: Session = Depends(get_db)):
    """Busca automática ao digitar o CPF no formulário público: se já
    existe cadastro deste CPF neste gabinete, devolve os dados para o
    JavaScript da tela preencher o resto do formulário sozinho — evita
    que a mesma pessoa seja recadastrada com nome diferente a cada novo
    pedido (ver AtendimentoPublicoService/EleitorService.
    criar_ou_atualizar_por_cpf). Nunca devolve nada fora deste gabinete
    (isolamento pelo public_token, igual a toda rota deste módulo), e
    nunca mais que {"encontrado": false} para CPF mal formatado,
    inexistente, token inválido/gabinete inativo, ou limite de tentativas
    excedido — a mesma resposta nesses quatro casos, de propósito, para
    não dar pista sobre qual deles é o motivo."""
    gabinete = _resolver_gabinete_ativo(db, public_token)
    if gabinete is None:
        return JSONResponse({"encontrado": False})

    ip_remoto = request.client.host if request.client else "desconhecido"
    if _limite_busca_cpf_excedido((ip_remoto, public_token)):
        return JSONResponse({"encontrado": False}, status_code=429)

    eleitor = EleitorService.obter_por_cpf(db, gabinete.id, cpf)
    if eleitor is None:
        return JSONResponse({"encontrado": False})

    return JSONResponse(
        {
            "encontrado": True,
            "nome": eleitor.nome,
            "whatsapp": eleitor.whatsapp or "",
            "telefone": eleitor.telefone or "",
            "email": eleitor.email or "",
            "bairro": eleitor.bairro or "",
            "cidade": eleitor.cidade or "",
        }
    )


def _contexto_formulario(
    db: Session, request: Request, public_token: str, gabinete: Gabinete, **extra
) -> dict:
    categorias = CategoriaService.listar_ativas(db, gabinete.id)
    subcategorias = SubcategoriaService.listar_ativas(db, gabinete.id)

    # Agrupado por categoria_id (string, chave de objeto JS/JSON) para a
    # cascata categoria -> subcategoria no template rodar 100% no cliente,
    # sem uma segunda rota/AJAX só para isso — módulo propositalmente leve.
    subcategorias_por_categoria: dict[str, list[dict]] = {}
    for subcategoria in subcategorias:
        chave = str(subcategoria.categoria_id)
        subcategorias_por_categoria.setdefault(chave, []).append(
            {"id": subcategoria.id, "nome": subcategoria.nome}
        )

    contexto = {
        "titulo": "Solicite atendimento",
        "gabinete": gabinete,
        "categorias": categorias,
        # .replace("</", "<\\/"): nomes de subcategoria são texto livre
        # cadastrado pelo próprio gabinete — improvável, mas um nome como
        # "</script><script>..." não pode fechar a tag antes da hora.
        "subcategorias_json": json.dumps(subcategorias_por_categoria).replace("</", "<\\/"),
        "erro": None,
        "dados": {},
        "csrf_token": _gerar_e_guardar_csrf(request, public_token),
        # Novo a cada renderização do formulário (GET, ou re-render após
        # erro) — nunca reoferece um submissao_token que já foi
        # reivindicado (ver AtendimentoPublicoService.
        # registrar_solicitacao_idempotente). Só um valor aleatório
        # opaco — não é gabinete_id/eleitor_id/timestamp/CPF nem deriva
        # deles, e só vira uma linha em SubmissoesCidadao no momento do
        # POST, nunca antes.
        "submissao_token": secrets.token_urlsafe(32),
    }
    contexto.update(extra)
    return contexto


@router.get("/{public_token}", response_class=HTMLResponse)
def formulario(request: Request, public_token: str, db: Session = Depends(get_db)):
    gabinete = _resolver_gabinete_ativo(db, public_token)
    if gabinete is None:
        return _pagina_indisponivel(request)
    return templates.TemplateResponse(
        request=request,
        name="cidadao/formulario.html",
        context=_contexto_formulario(db, request, public_token, gabinete),
    )


@router.post("/{public_token}", response_class=HTMLResponse)
def enviar(
    request: Request,
    public_token: str,
    csrf_token: str = Form(""),
    submissao_token: str = Form(""),
    nome: str = Form(...),
    cpf: str = Form(...),
    whatsapp: str = Form(...),
    telefone: str = Form(""),
    email: str = Form(""),
    cep: str = Form(""),
    logradouro: str = Form(""),
    numero: str = Form(""),
    complemento: str = Form(""),
    bairro: str = Form(""),
    cidade: str = Form(""),
    categoria_id: str = Form(""),
    subcategoria_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str = Form(...),
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    gabinete = _resolver_gabinete_ativo(db, public_token)
    if gabinete is None:
        return _pagina_indisponivel(request)

    dados_preenchidos = {
        "nome": nome,
        "cpf": cpf,
        "whatsapp": whatsapp,
        "telefone": telefone,
        "email": email,
        "cep": cep,
        "logradouro": logradouro,
        "numero": numero,
        "complemento": complemento,
        "bairro": bairro,
        "cidade": cidade,
        "categoria_id": categoria_id,
        "subcategoria_id": subcategoria_id,
        "titulo": titulo,
        "descricao": descricao,
    }

    # CSRF: validado ANTES de qualquer outra coisa — uma página externa
    # tentando induzir esse POST nunca teria como ler o token que só
    # existe dentro do HTML que o próprio SIGAB renderizou para esta
    # sessão (cookie assinado, SameSite=strict, o mesmo mecanismo já
    # usado pelo login — nenhuma configuração nova). Sem token
    # correspondente na sessão (ex.: sessão expirada) ou token
    # divergente: rejeitado, sem tocar em nada.
    if not _csrf_valido(request, public_token, csrf_token):
        return templates.TemplateResponse(
            request=request,
            name="cidadao/formulario.html",
            context=_contexto_formulario(
                db,
                request,
                public_token,
                gabinete,
                erro="Sua sessão expirou. Preencha o formulário novamente.",
                dados=dados_preenchidos,
            ),
            status_code=403,
        )

    if not submissao_token:
        return templates.TemplateResponse(
            request=request,
            name="cidadao/formulario.html",
            context=_contexto_formulario(
                db,
                request,
                public_token,
                gabinete,
                erro="Não foi possível registrar sua solicitação. Tente novamente.",
                dados=dados_preenchidos,
            ),
            status_code=400,
        )

    try:
        demanda, _reaproveitada = AtendimentoPublicoService.registrar_solicitacao_idempotente(
            db,
            gabinete,
            submissao_token,
            nome=nome,
            cpf=cpf,
            whatsapp=whatsapp,
            telefone=telefone,
            email=email,
            cep=cep,
            logradouro=logradouro,
            numero=numero,
            complemento=complemento,
            bairro=bairro,
            cidade=cidade,
            categoria_id=categoria_id or None,
            subcategoria_id=subcategoria_id or None,
            titulo=titulo,
            descricao=descricao,
            fotos=fotos,
        )
    except ValueError as error:
        # Validação de negócio (CPF inválido, categoria inválida etc.) —
        # o submissao_token que acabou de falhar nunca é reoferecido
        # (_contexto_formulario sempre gera um novo).
        return templates.TemplateResponse(
            request=request,
            name="cidadao/formulario.html",
            context=_contexto_formulario(
                db, request, public_token, gabinete, erro=str(error), dados=dados_preenchidos
            ),
            status_code=400,
        )
    except SolicitacaoEmProcessamentoError as error:
        return templates.TemplateResponse(
            request=request,
            name="cidadao/formulario.html",
            context=_contexto_formulario(
                db, request, public_token, gabinete, erro=str(error), dados=dados_preenchidos
            ),
            status_code=409,
        )
    except Exception:
        # Nunca vazar detalhe de banco/traceback para o cidadão — mensagem
        # genérica; o motivo real fica só no log do servidor.
        logger.exception("Falha ao registrar solicitação pública (gabinete_id=%s).", gabinete.id)
        return templates.TemplateResponse(
            request=request,
            name="cidadao/formulario.html",
            context=_contexto_formulario(
                db,
                request,
                public_token,
                gabinete,
                erro="Não foi possível registrar sua solicitação. Tente novamente.",
                dados=dados_preenchidos,
            ),
            status_code=500,
        )

    redirecionamento = RedirectResponse(f"/cidadao/{public_token}/confirmacao", status_code=303)
    # Cookie de curta duração só para carregar o protocolo na página de
    # confirmação após o redirect (padrão PRG — Post/Redirect/Get, o mesmo
    # já usado pelas mensagens flash do resto do sistema) — nunca uma rota
    # de consulta por ID (isso fica para uma etapa futura). Escopado ao
    # path deste token: não interfere com nenhum outro cookie do sistema.
    redirecionamento.set_cookie(
        COOKIE_PROTOCOLO,
        str(demanda.id),
        max_age=120,
        httponly=True,
        samesite="lax",
        path=f"/cidadao/{public_token}",
    )
    return redirecionamento


@router.get("/{public_token}/confirmacao", response_class=HTMLResponse)
def confirmacao(request: Request, public_token: str, db: Session = Depends(get_db)):
    gabinete = _resolver_gabinete_ativo(db, public_token)
    if gabinete is None:
        return _pagina_indisponivel(request)

    protocolo_bruto = request.cookies.get(COOKIE_PROTOCOLO)
    demanda_id = int(protocolo_bruto) if protocolo_bruto and protocolo_bruto.isdigit() else None

    if demanda_id is None:
        # Sem cookie válido (acesso direto à URL, cookie expirado etc.) —
        # nunca aceitar um id de demanda vindo de outro lugar (query
        # string, por exemplo): sem o cookie que só o próprio POST setou,
        # não há protocolo para mostrar.
        return RedirectResponse(f"/cidadao/{public_token}", status_code=303)

    demanda = db.get(Demanda, demanda_id)
    if demanda is None or demanda.gabinete_id != gabinete.id:
        return RedirectResponse(f"/cidadao/{public_token}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="cidadao/confirmacao.html",
        context={"titulo": "Solicitação registrada", "gabinete": gabinete, "demanda": demanda},
    )
