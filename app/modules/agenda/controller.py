from datetime import date, datetime, time
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, obter_contexto_atual
from app.core.database import get_db
from app.models.agenda import Agenda
from app.services.agenda_csv_service import AgendaCsvService
from app.services.agenda_service import STATUS_OPCOES, AgendaService
from app.services.eleitor_service import EleitorService

router = APIRouter(prefix="/agenda", tags=["Agenda"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def flash_message(
    message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse("/agenda", status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", message, max_age=10, httponly=True, path="/agenda", samesite="lax"
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/agenda", samesite="lax"
        )
    return redirect


def _opcoes_formulario(db: Session) -> dict:
    return {
        "status_opcoes": STATUS_OPCOES,
    }


def _para_formulario(compromisso: Agenda) -> SimpleNamespace:
    return SimpleNamespace(
        id=compromisso.id,
        eleitor_id=compromisso.eleitor_id,
        titulo=compromisso.titulo,
        descricao=compromisso.descricao,
        data=compromisso.inicio.date() if compromisso.inicio else None,
        hora_inicio=compromisso.inicio.time() if compromisso.inicio else None,
        hora_fim=compromisso.fim.time() if compromisso.fim else None,
        local=compromisso.local,
        responsavel=compromisso.responsavel,
        telefone_contato=compromisso.telefone_contato,
        status=compromisso.status,
    )


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    pesquisa: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    compromissos, pagina_atual, total_paginas = AgendaService.listar(
        db, contexto.gabinete_id, pesquisa, pagina
    )
    resposta = templates.TemplateResponse(
        request=request,
        name="agenda/lista.html",
        context={
            "titulo": "Agenda",
            "compromissos": compromissos,
            "agora": datetime.now(),
            "pesquisa": pesquisa,
            "pagina_atual": pagina_atual,
            "total_paginas": total_paginas,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/agenda")
    resposta.delete_cookie("flash_category", path="/agenda")
    return resposta


@router.get("/importar", response_class=HTMLResponse)
def importar_pagina(request: Request, contexto: ContextoSessao = Depends(obter_contexto_atual)):
    return templates.TemplateResponse(
        request=request,
        name="agenda/importar.html",
        context={"titulo": "Importar agenda", "resultado": None},
    )


@router.post("/importar", response_class=HTMLResponse)
def importar_csv(
    request: Request,
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    # Rota síncrona de propósito — ver comentário equivalente em
    # app/modules/eleitores/controller.py:importar_csv().
    conteudo = arquivo.file.read()
    resultado = AgendaCsvService.importar_compromisso_historico(db, contexto.gabinete_id, conteudo)
    return templates.TemplateResponse(
        request=request,
        name="agenda/importar.html",
        context={"titulo": "Importar agenda", "resultado": resultado},
    )


@router.get("/novo", response_class=HTMLResponse)
def novo(
    request: Request,
    pesquisa_eleitor: str = "",
    selecionar_eleitor_id: int | None = None,
    sem_eleitor: bool = False,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    eleitor_atual, eleitor_resolvido = EleitorService.resolver_selecao(
        db, contexto.gabinete_id, selecionar_eleitor_id, sem_eleitor=sem_eleitor
    )
    resultados_busca_eleitor = []
    if not eleitor_resolvido and pesquisa_eleitor.strip():
        resultados_busca_eleitor, _, _ = EleitorService.listar(
            db, contexto.gabinete_id, pesquisa_eleitor, 1
        )

    return templates.TemplateResponse(
        request=request,
        name="agenda/formulario.html",
        context={
            "titulo": "Novo compromisso",
            "compromisso": None,
            "eleitor_atual": eleitor_atual,
            "eleitor_resolvido": eleitor_resolvido,
            "obrigatorio": False,
            "acao_busca": "/agenda/novo",
            "pesquisa_eleitor": pesquisa_eleitor,
            "resultados_busca_eleitor": resultados_busca_eleitor,
            **_opcoes_formulario(db),
        },
    )


@router.post("/novo")
def criar(
    request: Request,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    data: date | None = Form(None),
    hora_inicio: time | None = Form(None),
    hora_fim: time | None = Form(None),
    local: str | None = Form(None),
    responsavel: str | None = Form(None),
    telefone_contato: str | None = Form(None),
    status: str | None = Form(None),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    try:
        AgendaService.criar(
            db,
            contexto.gabinete_id,
            titulo,
            descricao,
            data,
            hora_inicio,
            hora_fim,
            local,
            responsavel,
            telefone_contato,
            status,
            eleitor_id,
        )
    except ValueError as error:
        compromisso_preenchido = SimpleNamespace(
            id=None,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            data=data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim,
            local=local,
            responsavel=responsavel,
            telefone_contato=telefone_contato,
            status=status,
        )
        eleitor_atual = (
            EleitorService.obter_por_id(db, contexto.gabinete_id, compromisso_preenchido.eleitor_id)
            if compromisso_preenchido.eleitor_id
            else None
        )
        return templates.TemplateResponse(
            request=request,
            name="agenda/formulario.html",
            context={
                "titulo": "Novo compromisso",
                "compromisso": compromisso_preenchido,
                "eleitor_atual": eleitor_atual,
                "eleitor_resolvido": True,
                "obrigatorio": False,
                "acao_busca": "/agenda/novo",
                "pesquisa_eleitor": "",
                "resultados_busca_eleitor": [],
                "erro": str(error),
                **_opcoes_formulario(db),
            },
            status_code=400,
        )
    return flash_message("Compromisso cadastrado.", "success")


@router.get("/{agenda_id}", response_class=HTMLResponse)
def visualizar(
    request: Request,
    agenda_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    compromisso = AgendaService.obter_por_id(db, contexto.gabinete_id, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")
    return templates.TemplateResponse(
        request=request,
        name="agenda/visualizar.html",
        context={"titulo": compromisso.titulo, "compromisso": compromisso},
    )


@router.get("/{agenda_id}/editar", response_class=HTMLResponse)
def editar(
    request: Request,
    agenda_id: int,
    pesquisa_eleitor: str = "",
    selecionar_eleitor_id: int | None = None,
    trocar_eleitor: bool = False,
    sem_eleitor: bool = False,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    compromisso = AgendaService.obter_por_id(db, contexto.gabinete_id, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")

    eleitor_atual, eleitor_resolvido = EleitorService.resolver_selecao(
        db,
        contexto.gabinete_id,
        selecionar_eleitor_id,
        compromisso.eleitor_id,
        trocar_eleitor,
        sem_eleitor,
        ja_existe=True,
    )
    resultados_busca_eleitor = []
    if not eleitor_resolvido and pesquisa_eleitor.strip():
        resultados_busca_eleitor, _, _ = EleitorService.listar(
            db, contexto.gabinete_id, pesquisa_eleitor, 1
        )

    return templates.TemplateResponse(
        request=request,
        name="agenda/formulario.html",
        context={
            "titulo": "Editar compromisso",
            "compromisso": _para_formulario(compromisso),
            "eleitor_atual": eleitor_atual,
            "eleitor_resolvido": eleitor_resolvido,
            "obrigatorio": False,
            "acao_busca": f"/agenda/{agenda_id}/editar",
            "pesquisa_eleitor": pesquisa_eleitor,
            "resultados_busca_eleitor": resultados_busca_eleitor,
            **_opcoes_formulario(db),
        },
    )


@router.post("/{agenda_id}/editar")
def atualizar(
    request: Request,
    agenda_id: int,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    data: date | None = Form(None),
    hora_inicio: time | None = Form(None),
    hora_fim: time | None = Form(None),
    local: str | None = Form(None),
    responsavel: str | None = Form(None),
    telefone_contato: str | None = Form(None),
    status: str | None = Form(None),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    compromisso = AgendaService.obter_por_id(db, contexto.gabinete_id, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")
    try:
        AgendaService.atualizar(
            db,
            compromisso,
            titulo,
            descricao,
            data,
            hora_inicio,
            hora_fim,
            local,
            responsavel,
            telefone_contato,
            status,
            eleitor_id,
        )
    except ValueError as error:
        compromisso_preenchido = SimpleNamespace(
            id=agenda_id,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            data=data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim,
            local=local,
            responsavel=responsavel,
            telefone_contato=telefone_contato,
            status=status,
        )
        eleitor_atual = (
            EleitorService.obter_por_id(db, contexto.gabinete_id, compromisso_preenchido.eleitor_id)
            if compromisso_preenchido.eleitor_id
            else None
        )
        return templates.TemplateResponse(
            request=request,
            name="agenda/formulario.html",
            context={
                "titulo": "Editar compromisso",
                "compromisso": compromisso_preenchido,
                "eleitor_atual": eleitor_atual,
                "eleitor_resolvido": True,
                "obrigatorio": False,
                "acao_busca": f"/agenda/{agenda_id}/editar",
                "pesquisa_eleitor": "",
                "resultados_busca_eleitor": [],
                "erro": str(error),
                **_opcoes_formulario(db),
            },
            status_code=400,
        )
    return flash_message("Compromisso atualizado.", "success")


@router.post("/{agenda_id}/excluir")
def excluir(
    agenda_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    compromisso = AgendaService.obter_por_id(db, contexto.gabinete_id, agenda_id)
    if compromisso is None:
        return flash_message("Compromisso não encontrado.")
    AgendaService.excluir(db, compromisso)
    return flash_message("Compromisso excluído.", "success")
