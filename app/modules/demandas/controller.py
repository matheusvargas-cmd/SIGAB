import json
from datetime import date
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, obter_contexto_atual
from app.core.database import get_db
from app.core.flash import codificar_flash, decodificar_flash
from app.models.categoria import Categoria
from app.models.subcategoria import Subcategoria
from app.services.agenda_service import AgendaService
from app.services.categoria_service import CategoriaService
from app.services.demanda_anexo_service import DemandaAnexoService
from app.services.demanda_csv_service import DemandaCsvService
from app.services.demanda_service import (
    PRIORIDADE_OPCOES,
    STATUS_OPCOES,
    DemandaService,
)
from app.services.eleitor_service import EleitorService
from app.services.storage_service import StorageError, obter_storage_service
from app.services.subcategoria_service import SubcategoriaService

router = APIRouter(prefix="/demandas", tags=["Demandas"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def flash_message(
    message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse("/demandas", status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", codificar_flash(message), max_age=10, httponly=True,
            path="/demandas", samesite="lax",
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/demandas", samesite="lax"
        )
    return redirect


def _opcoes_formulario(
    db: Session,
    gabinete_id: int,
    categoria_atual: Categoria | None = None,
    subcategoria_atual: Subcategoria | None = None,
) -> dict:
    categorias = CategoriaService.listar_ativas(db, gabinete_id)
    if categoria_atual and not categoria_atual.ativo and categoria_atual.id not in {
        categoria.id for categoria in categorias
    }:
        categorias = categorias + [categoria_atual]

    subcategoria_por_categoria: dict[int, list[dict]] = {}
    for subcategoria in SubcategoriaService.listar_ativas(db, gabinete_id):
        subcategoria_por_categoria.setdefault(subcategoria.categoria_id, []).append(
            {"id": subcategoria.id, "nome": subcategoria.nome}
        )
    if subcategoria_atual and not subcategoria_atual.ativo:
        lista = subcategoria_por_categoria.setdefault(subcategoria_atual.categoria_id, [])
        if not any(item["id"] == subcategoria_atual.id for item in lista):
            lista.append({"id": subcategoria_atual.id, "nome": subcategoria_atual.nome})

    return {
        "categorias": categorias,
        "subcategoria_por_categoria_json": json.dumps(subcategoria_por_categoria),
        "status_opcoes": STATUS_OPCOES,
        "prioridade_opcoes": PRIORIDADE_OPCOES,
    }


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    pesquisa: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demandas, pagina_atual, total_paginas = DemandaService.listar(
        db, contexto.gabinete_id, pesquisa, pagina
    )
    resposta = templates.TemplateResponse(
        request=request,
        name="demandas/lista.html",
        context={
            "titulo": "Demandas",
            "demandas": demandas,
            "pesquisa": pesquisa,
            "pagina_atual": pagina_atual,
            "total_paginas": total_paginas,
            "flash_message": decodificar_flash(request.cookies.get("flash_message")),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/demandas")
    resposta.delete_cookie("flash_category", path="/demandas")
    return resposta


@router.get("/importar", response_class=HTMLResponse)
def importar_pagina(request: Request, contexto: ContextoSessao = Depends(obter_contexto_atual)):
    return templates.TemplateResponse(
        request=request,
        name="demandas/importar.html",
        context={"titulo": "Importar demandas", "resultado": None},
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
    resultado = DemandaCsvService.importar_atendimento_historico(db, contexto.gabinete_id, conteudo)
    return templates.TemplateResponse(
        request=request,
        name="demandas/importar.html",
        context={"titulo": "Importar demandas", "resultado": resultado},
    )


@router.get("/novo", response_class=HTMLResponse)
def novo(
    request: Request,
    pesquisa_eleitor: str = "",
    selecionar_eleitor_id: int | None = None,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    eleitor_atual, eleitor_resolvido = EleitorService.resolver_selecao(
        db, contexto.gabinete_id, selecionar_eleitor_id
    )
    resultados_busca_eleitor = []
    if not eleitor_resolvido and pesquisa_eleitor.strip():
        resultados_busca_eleitor, _, _ = EleitorService.listar(
            db, contexto.gabinete_id, pesquisa_eleitor, 1
        )

    return templates.TemplateResponse(
        request=request,
        name="demandas/formulario.html",
        context={
            "titulo": "Nova demanda",
            "demanda": None,
            "eleitor_atual": eleitor_atual,
            "eleitor_resolvido": eleitor_resolvido,
            "obrigatorio": True,
            "acao_busca": "/demandas/novo",
            "pesquisa_eleitor": pesquisa_eleitor,
            "resultados_busca_eleitor": resultados_busca_eleitor,
            **_opcoes_formulario(db, contexto.gabinete_id),
        },
    )


@router.post("/novo")
def criar(
    request: Request,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    categoria_id: str | None = Form(None),
    subcategoria_id: str | None = Form(None),
    status: str | None = Form(None),
    prioridade: str | None = Form(None),
    responsavel: str | None = Form(None),
    prazo: date | None = Form(None),
    observacoes_internas: str | None = Form(None),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    try:
        DemandaService.criar(
            db,
            contexto.gabinete_id,
            eleitor_id,
            titulo,
            descricao,
            categoria_id,
            subcategoria_id,
            status,
            prioridade,
            responsavel,
            prazo,
            observacoes_internas,
        )
    except ValueError as error:
        demanda_preenchida = SimpleNamespace(
            id=None,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            categoria_id=int(categoria_id) if categoria_id and categoria_id.isdigit() else None,
            subcategoria_id=int(subcategoria_id)
            if subcategoria_id and subcategoria_id.isdigit()
            else None,
            status=status,
            prioridade=prioridade,
            responsavel=responsavel,
            prazo=prazo,
            observacoes_internas=observacoes_internas,
        )
        eleitor_atual = (
            EleitorService.obter_por_id(db, contexto.gabinete_id, demanda_preenchida.eleitor_id)
            if demanda_preenchida.eleitor_id
            else None
        )
        categoria_atual = (
            CategoriaService.obter_por_id(db, contexto.gabinete_id, demanda_preenchida.categoria_id)
            if demanda_preenchida.categoria_id
            else None
        )
        subcategoria_atual = (
            SubcategoriaService.obter_por_id(
                db, contexto.gabinete_id, demanda_preenchida.subcategoria_id
            )
            if demanda_preenchida.subcategoria_id
            else None
        )
        return templates.TemplateResponse(
            request=request,
            name="demandas/formulario.html",
            context={
                "titulo": "Nova demanda",
                "demanda": demanda_preenchida,
                "eleitor_atual": eleitor_atual,
                "eleitor_resolvido": True,
                "obrigatorio": True,
                "acao_busca": "/demandas/novo",
                "pesquisa_eleitor": "",
                "resultados_busca_eleitor": [],
                "erro": str(error),
                **_opcoes_formulario(db, contexto.gabinete_id, categoria_atual, subcategoria_atual),
            },
            status_code=400,
        )
    return flash_message("Demanda cadastrada.", "success")


@router.get("/{demanda_id}", response_class=HTMLResponse)
def visualizar(
    request: Request,
    demanda_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")
    eleitor = (
        EleitorService.obter_por_id(db, contexto.gabinete_id, demanda.eleitor_id)
        if demanda.eleitor_id
        else None
    )
    compromisso_retorno = AgendaService.obter_por_demanda(db, contexto.gabinete_id, demanda.id)
    anexos = DemandaAnexoService.listar_por_demanda(db, contexto.gabinete_id, demanda.id)
    return templates.TemplateResponse(
        request=request,
        name="demandas/visualizar.html",
        context={
            "titulo": demanda.titulo,
            "demanda": demanda,
            "eleitor": eleitor,
            "compromisso_retorno": compromisso_retorno,
            "anexos": anexos,
        },
    )


@router.get("/{demanda_id}/anexos/{anexo_id}")
def abrir_anexo(
    demanda_id: int,
    anexo_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    # Dupla checagem de propósito (nunca confiar só no anexo_id): tanto a
    # demanda quanto o anexo precisam pertencer ao gabinete autenticado, e
    # o anexo precisa mesmo pertencer a ESTA demanda — nenhuma URL
    # temporária é gerada antes dessas três checagens passarem. Ver
    # Prompt 3, seção 14 (isolamento multi-tenant) e 16 (autorização antes
    # da geração da URL).
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    anexo = DemandaAnexoService.obter_por_id(db, contexto.gabinete_id, anexo_id)
    if (
        demanda is None
        or anexo is None
        or anexo.demanda_id != demanda.id
        or not anexo.arquivo_disponivel
    ):
        return flash_message("Anexo não encontrado.")

    storage = obter_storage_service()
    if storage is None:
        return flash_message("O armazenamento de fotos não está configurado neste ambiente.")

    try:
        url = storage.gerar_url_temporaria(anexo.storage_key)
    except StorageError:
        return flash_message("Não foi possível abrir o anexo. Tente novamente.")
    return RedirectResponse(url, status_code=302)


@router.get("/{demanda_id}/editar", response_class=HTMLResponse)
def editar(
    request: Request,
    demanda_id: int,
    pesquisa_eleitor: str = "",
    selecionar_eleitor_id: int | None = None,
    trocar_eleitor: bool = False,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")

    eleitor_atual, eleitor_resolvido = EleitorService.resolver_selecao(
        db, contexto.gabinete_id, selecionar_eleitor_id, demanda.eleitor_id, trocar_eleitor
    )
    resultados_busca_eleitor = []
    if not eleitor_resolvido and pesquisa_eleitor.strip():
        resultados_busca_eleitor, _, _ = EleitorService.listar(
            db, contexto.gabinete_id, pesquisa_eleitor, 1
        )

    return templates.TemplateResponse(
        request=request,
        name="demandas/formulario.html",
        context={
            "titulo": "Editar demanda",
            "demanda": demanda,
            "eleitor_atual": eleitor_atual,
            "eleitor_resolvido": eleitor_resolvido,
            "obrigatorio": True,
            "acao_busca": f"/demandas/{demanda_id}/editar",
            "pesquisa_eleitor": pesquisa_eleitor,
            "resultados_busca_eleitor": resultados_busca_eleitor,
            **_opcoes_formulario(
                db, contexto.gabinete_id, demanda.categoria_vinculada, demanda.subcategoria_vinculada
            ),
        },
    )


@router.post("/{demanda_id}/editar")
def atualizar(
    request: Request,
    demanda_id: int,
    eleitor_id: str = Form(""),
    titulo: str = Form(...),
    descricao: str | None = Form(None),
    categoria_id: str | None = Form(None),
    subcategoria_id: str | None = Form(None),
    status: str | None = Form(None),
    prioridade: str | None = Form(None),
    responsavel: str | None = Form(None),
    prazo: date | None = Form(None),
    observacoes_internas: str | None = Form(None),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")

    status_anterior = demanda.status
    try:
        DemandaService.atualizar(
            db,
            demanda,
            eleitor_id,
            titulo,
            descricao,
            categoria_id,
            subcategoria_id,
            status,
            prioridade,
            responsavel,
            prazo,
            observacoes_internas,
        )
    except ValueError as error:
        demanda_preenchida = SimpleNamespace(
            id=demanda_id,
            eleitor_id=int(eleitor_id) if eleitor_id.isdigit() else None,
            titulo=titulo,
            descricao=descricao,
            categoria_id=int(categoria_id) if categoria_id and categoria_id.isdigit() else None,
            subcategoria_id=int(subcategoria_id)
            if subcategoria_id and subcategoria_id.isdigit()
            else None,
            status=status,
            prioridade=prioridade,
            responsavel=responsavel,
            prazo=prazo,
            observacoes_internas=observacoes_internas,
        )
        eleitor_atual = (
            EleitorService.obter_por_id(db, contexto.gabinete_id, demanda_preenchida.eleitor_id)
            if demanda_preenchida.eleitor_id
            else None
        )
        categoria_atual = (
            CategoriaService.obter_por_id(db, contexto.gabinete_id, demanda_preenchida.categoria_id)
            if demanda_preenchida.categoria_id
            else None
        )
        subcategoria_atual = (
            SubcategoriaService.obter_por_id(
                db, contexto.gabinete_id, demanda_preenchida.subcategoria_id
            )
            if demanda_preenchida.subcategoria_id
            else None
        )
        return templates.TemplateResponse(
            request=request,
            name="demandas/formulario.html",
            context={
                "titulo": "Editar demanda",
                "demanda": demanda_preenchida,
                "eleitor_atual": eleitor_atual,
                "eleitor_resolvido": True,
                "obrigatorio": True,
                "acao_busca": f"/demandas/{demanda_id}/editar",
                "pesquisa_eleitor": "",
                "resultados_busca_eleitor": [],
                "erro": str(error),
                **_opcoes_formulario(db, contexto.gabinete_id, categoria_atual, subcategoria_atual),
            },
            status_code=400,
        )

    if status_anterior != "Concluído" and demanda.status == "Concluído":
        return flash_message("Demanda concluída.", "success")
    return flash_message("Demanda atualizada.", "success")


@router.post("/{demanda_id}/excluir")
def excluir(
    demanda_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.")
    DemandaService.excluir(db, demanda)
    return flash_message("Demanda excluída.", "success")
