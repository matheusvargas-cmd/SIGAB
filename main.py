import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import app.models  # noqa: F401 — garante que todo model é conhecido por Base.metadata
from app.core.config import APP_NAME, STATIC_DIR, settings
from app.core.contexto import GabineteNaoSelecionado, NaoAutenticado, SemPermissao
from app.core.database import Base, engine
from app.services.migration_service import MigrationService

from app.modules.agenda.controller import router as agenda_router
from app.modules.auth.controller import router as auth_router
from app.modules.configuracoes.controller import router as configuracoes_router
from app.modules.dashboard.controller import router as dashboard_router
from app.modules.demandas.controller import router as demandas_router
from app.modules.eleitores.controller import router as eleitores_router
from app.modules.gabinete.controller import router as gabinete_router
from app.modules.relatorios.controller import router as relatorios_router
from app.modules.usuarios.controller import router as usuarios_router

logger = logging.getLogger(__name__)

# Interrompe o boot fora de ambiente=local se a SECRET_KEY ainda for o valor
# de desenvolvimento — ver docstring de exigir_secret_key_segura(). As
# demais checagens (DEBUG, SQLite fora de local) continuam só como aviso.
settings.exigir_secret_key_segura()
for aviso in settings.validar_producao():
    logger.warning(aviso)

# Evolução de schema em homologação/produção é responsabilidade exclusiva do
# Alembic (`alembic upgrade head`, executado no deploy, antes de subir a
# aplicação) — combinado explicitamente na Fase 1: produção nunca depende de
# create_all()/ALTER TABLE automático disparado pelo main.py. Esses métodos
# só rodam para o banco SQLite local (instalação desktop de sempre), onde
# nunca existiu um passo de deploy separado e o boot sempre foi o único
# lugar em que o schema se atualiza.
if settings.is_sqlite:
    Base.metadata.create_all(bind=engine)
    MigrationService.atualizar_schema_eleitores()
    MigrationService.atualizar_schema_demandas()
    MigrationService.relaxar_eleitor_obrigatorio_demandas()
    MigrationService.adicionar_gabinete_id()
    MigrationService.atualizar_schema_agenda()
    MigrationService.semear_categorias_padrao()
    MigrationService.vincular_categoria_id_demandas()
    MigrationService.semear_categorias_atendimento_historico()
    MigrationService.semear_categorias_demandas_reais()
    MigrationService.garantir_gabinete_padrao_local()

# debug=True liga páginas de erro do Starlette com traceback completo (e
# variáveis locais) direto no navegador — nunca aceitável fora de
# desenvolvimento local. `and settings.ambiente == "local"` é uma segunda
# trava independente do valor de DEBUG no ambiente: mesmo que alguém
# configure DEBUG=true por engano em homologação/produção, isso sozinho não
# liga o traceback público.
app = FastAPI(title=APP_NAME, debug=settings.debug and settings.ambiente == "local")

# Sessão assinada (itsdangerous) via cookie — guarda só usuario_id/gabinete_id,
# nunca dado sensível nem perfil (perfil é sempre revalidado no banco a cada
# requisição, ver app/core/contexto.py). SameSite=strict é a defesa contra
# CSRF adotada nesta fase: como o app é 100% servido pelo próprio backend
# (sem formulário de terceiro submetendo para o SIGAB), um cookie que nunca
# acompanha requisição cross-site elimina o CSRF por definição, sem precisar
# de token sincronizador espalhado por cada formulário. O único custo é um
# link direto de fora exigir novo login mesmo para GET — aceitável para uma
# ferramenta interna de gabinete.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="sigab_session",
    max_age=settings.sessao_max_idade_segundos,
    same_site="strict",
    https_only=settings.cookie_secure,
)


@app.exception_handler(NaoAutenticado)
async def _redirecionar_login(request: Request, exc: NaoAutenticado):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(GabineteNaoSelecionado)
async def _redirecionar_selecionar_gabinete(request: Request, exc: GabineteNaoSelecionado):
    return RedirectResponse("/selecionar-gabinete", status_code=303)


@app.exception_handler(SemPermissao)
async def _sem_permissao(request: Request, exc: SemPermissao):
    from fastapi.templating import Jinja2Templates

    from app.core.config import TEMPLATES_DIR

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    return templates.TemplateResponse(
        request=request,
        name="auth/sem_permissao.html",
        context={"titulo": "Acesso não permitido"},
        status_code=403,
    )


# Usado só pelo build standalone (launcher/conecta360_standalone.py) para
# encerrar o servidor automaticamente quando nenhuma aba do navegador está
# mais aberta. Em desenvolvimento (uvicorn main:app) esse estado existe mas
# não é lido por ninguém — não altera nenhum comportamento existente.
app.state.ultimo_heartbeat = time.time()


@app.post("/_heartbeat")
def heartbeat() -> dict:
    app.state.ultimo_heartbeat = time.time()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(eleitores_router)
app.include_router(demandas_router)
app.include_router(agenda_router)
app.include_router(relatorios_router)
app.include_router(configuracoes_router)
app.include_router(usuarios_router)
app.include_router(gabinete_router)
