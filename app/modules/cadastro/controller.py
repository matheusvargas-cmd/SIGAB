import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.core.security import gerar_hash_senha
from app.services.assinatura_service import PLANOS
from app.services.gabinete_service import GabineteService
from app.services.usuario_service import UsuarioService

# Autocadastro público (Fase 3) — porta de entrada paralela ao /login, nunca
# uma variação de /superadmin: aqui não há exigir_superadmin nem
# ContextoSessao, o gabinete ainda não existe quando a requisição chega.
# Reaproveita integralmente GabineteService.criar_gabinete_com_admin (mesma
# regra de TRIAL de 7 dias do Superadmin/script de bootstrap) — este
# controller só valida entrada pública e decide sessão/redirecionamento,
# nunca recalcula status_assinatura/assinatura_vencimento.
router = APIRouter(tags=["Autocadastro"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

NOME_MINIMO_CARACTERES = 2
NOME_MAXIMO_CARACTERES = 150
EMAIL_MAXIMO_CARACTERES = 150
SENHA_MINIMO_CARACTERES = 8
SENHA_MAXIMO_CARACTERES = 128

CHAVE_SESSAO_CSRF = "cadastro_csrf"

# Mensagem única para TODA falha relacionada a e-mail já cadastrado (ou à
# corrida rara entre o pré-check e o commit) — nunca "este e-mail já tem
# conta", que permitiria varrer e-mails cadastrados só observando a
# resposta. Os demais erros de validação (nome/senha/confirmação) continuam
# com mensagem específica porque não revelam se alguma conta já existe.
MENSAGEM_ERRO_GENERICA = (
    "Não foi possível concluir o cadastro com os dados informados. "
    "Revise os campos e tente novamente."
)

# Mesmo princípio de AuthService._HASH_FICTICIO: gerar este hash gasta
# aproximadamente o mesmo tempo de CPU que gerar_hash_senha(senha_admin) no
# caminho de sucesso, para que descobrir "este e-mail já existe" não fique
# mensurável pelo tempo de resposta quando a única diferença visível é a
# mesma mensagem genérica.
_SENHA_FICTICIA = "senha-ficticia-somente-para-normalizar-tempo-de-resposta"


def _plano_da_query(request: Request) -> str | None:
    """Lê "plano" só da querystring (nunca de Form) — o valor só decide
    para onde redirecionar depois do cadastro (UX), nunca o que é
    cobrado (isso continua sendo exclusivamente o botão clicado em
    /assinatura/checkout, inalterado). Allowlist estrita: qualquer coisa
    fora de PLANOS (reaproveitado de assinatura_service, nunca uma
    segunda lista de planos) vira None — mesmo comportamento de "sem
    plano", nunca um erro."""
    valor = (request.query_params.get("plano") or "").strip().upper()
    return valor if valor in PLANOS else None


def _gerar_e_guardar_csrf(request: Request) -> str:
    token = secrets.token_urlsafe(32)
    request.session[CHAVE_SESSAO_CSRF] = token
    return token


def _csrf_valido(request: Request, token_recebido: str) -> bool:
    token_esperado = request.session.get(CHAVE_SESSAO_CSRF)
    if not token_esperado or not token_recebido:
        return False
    return secrets.compare_digest(token_esperado, token_recebido)


def _validar_campos(
    nome_gabinete: str, nome_admin: str, email: str, senha: str, confirmar_senha: str
) -> str | None:
    if len(nome_admin) < NOME_MINIMO_CARACTERES or len(nome_admin) > NOME_MAXIMO_CARACTERES:
        return "Informe um nome válido."
    if len(nome_gabinete) < NOME_MINIMO_CARACTERES or len(nome_gabinete) > NOME_MAXIMO_CARACTERES:
        return "Informe um nome de gabinete válido."
    if "@" not in email or len(email) < 3 or len(email) > EMAIL_MAXIMO_CARACTERES:
        return "Informe um e-mail válido."
    if len(senha) < SENHA_MINIMO_CARACTERES:
        return f"A senha deve ter pelo menos {SENHA_MINIMO_CARACTERES} caracteres."
    if len(senha) > SENHA_MAXIMO_CARACTERES:
        return f"A senha deve ter no máximo {SENHA_MAXIMO_CARACTERES} caracteres."
    if senha != confirmar_senha:
        return "As senhas informadas não coincidem."
    return None


def _formulario(
    request: Request, *, erro: str | None, dados: dict, status_code: int = 200, plano: str | None = None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="cadastro/formulario.html",
        context={
            "titulo": "Criar conta gratuita",
            "erro": erro,
            "dados": dados,
            "csrf_token": _gerar_e_guardar_csrf(request),
            "plano": plano,
        },
        status_code=status_code,
    )


@router.get("/cadastro", response_class=HTMLResponse)
def formulario_cadastro(request: Request):
    if request.session.get("usuario_id"):
        # Já autenticado — nunca mostra o formulário de criar-outro-gabinete
        # aqui; quem quer um gabinete adicional passa por /superadmin (fora
        # do alcance do autocadastro público).
        return RedirectResponse("/", status_code=303)
    return _formulario(request, erro=None, dados={}, plano=_plano_da_query(request))


@router.post("/cadastro", response_class=HTMLResponse)
def criar_cadastro(
    request: Request,
    nome_gabinete: str = Form(""),
    nome_admin: str = Form(""),
    email_admin: str = Form(""),
    senha_admin: str = Form(""),
    confirmar_senha: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    # gabinete_id e super_admin nunca são parâmetros desta função: qualquer
    # valor enviado artificialmente no corpo do POST para esses nomes é
    # descartado pelo FastAPI antes deste código rodar — o tenant é sempre
    # criado do zero pelo servidor (GabineteService.criar_gabinete_com_admin
    # gera o Gabinete e o public_token internamente) e o Usuario criado aqui
    # nunca recebe super_admin=True (nem é oferecido como opção no form).
    plano = _plano_da_query(request)

    if request.session.get("usuario_id"):
        # Sessão já autenticada tentando submeter o formulário (ex.: aba
        # antiga, duplo submit) — nunca cria um segundo gabinete em
        # silêncio; ignora o corpo da requisição e manda para a área logada.
        return RedirectResponse("/", status_code=303)

    dados_echo = {
        "nome_gabinete": nome_gabinete,
        "nome_admin": nome_admin,
        "email_admin": email_admin,
    }

    if not _csrf_valido(request, csrf_token):
        return _formulario(request, erro=MENSAGEM_ERRO_GENERICA, dados=dados_echo, status_code=400, plano=plano)

    nome_gabinete_normalizado = (nome_gabinete or "").strip()
    nome_admin_normalizado = (nome_admin or "").strip()
    email_normalizado = (email_admin or "").strip().lower()
    senha = senha_admin or ""

    erro = _validar_campos(
        nome_gabinete_normalizado, nome_admin_normalizado, email_normalizado, senha, confirmar_senha
    )
    if erro:
        return _formulario(request, erro=erro, dados=dados_echo, status_code=400, plano=plano)

    if UsuarioService.buscar_usuario_por_email(db, email_normalizado) is not None:
        gerar_hash_senha(_SENHA_FICTICIA)
        return _formulario(request, erro=MENSAGEM_ERRO_GENERICA, dados=dados_echo, status_code=400, plano=plano)

    try:
        gabinete = GabineteService.criar_gabinete_com_admin(
            db, nome_gabinete_normalizado, None, nome_admin_normalizado, email_normalizado, senha
        )
    except ValueError:
        # Cobre a corrida rara entre o pré-check acima e o commit (dois
        # cadastros simultâneos com o mesmo e-mail): o service detecta a
        # duplicidade de novo, antes de qualquer insert — mesma mensagem
        # genérica, nunca a específica do service ("Já existe um usuário
        # com este e-mail.").
        return _formulario(request, erro=MENSAGEM_ERRO_GENERICA, dados=dados_echo, status_code=400, plano=plano)
    except IntegrityError:
        db.rollback()
        return _formulario(request, erro=MENSAGEM_ERRO_GENERICA, dados=dados_echo, status_code=400, plano=plano)

    usuario = UsuarioService.buscar_usuario_por_email(db, email_normalizado)

    request.session.clear()
    request.session["usuario_id"] = usuario.id
    request.session["gabinete_id"] = gabinete.id

    # Mesmo mecanismo de sessão do POST /login (app/modules/auth/controller.py)
    # — nenhuma sessão paralela: só os dois valores que obter_contexto_atual
    # já sabe ler, revalidados no banco a cada requisição como qualquer
    # outra sessão.
    if plano is not None:
        # Contratação direta (Fase 4): o gabinete já nasceu em TRIAL (nada
        # muda nisso) e o usuário já está autenticado no gabinete certo —
        # só falta levá-lo até o Checkout. /assinatura/checkout continua
        # inteiramente inalterado: lê gabinete_id exclusivamente da sessão
        # (nunca deste "plano"), então o Checkout criado ali só pode
        # pertencer a este gabinete recém-criado. O próprio usuário ainda
        # escolhe/confirma o plano clicando um dos botões em /assinatura —
        # este redirecionamento é só uma sugestão de navegação, nunca uma
        # cobrança ou ativação.
        return RedirectResponse(f"/assinatura?plano={plano.lower()}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="cadastro/sucesso.html",
        context={"titulo": "Cadastro concluído", "nome_gabinete": gabinete.nome},
    )
