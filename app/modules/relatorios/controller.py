import csv
import io
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.services.agenda_service import STATUS_OPCOES as AGENDA_STATUS_OPCOES
from app.services.agenda_service import AgendaService
from app.services.categoria_service import CategoriaService
from app.services.demanda_service import PRIORIDADE_OPCOES
from app.services.demanda_service import STATUS_OPCOES as DEMANDA_STATUS_OPCOES
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService

router = APIRouter(prefix="/relatorios", tags=["Relatórios"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _data(valor: str | None) -> date | None:
    if not valor or not valor.strip():
        return None
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        return None


def _query_string(**kwargs) -> str:
    valores = {chave: valor for chave, valor in kwargs.items() if valor not in (None, "")}
    return urlencode(valores)


def _csv_response(cabecalho: list[str], linhas: list[list], nome_arquivo: str) -> Response:
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@router.get("", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(
        request=request, name="relatorios/index.html", context={"titulo": "Relatórios"}
    )


# ---------- P1.1 — Demandas por status ----------


@router.get("/demandas-por-status", response_class=HTMLResponse)
def demandas_por_status(
    request: Request,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    categoria: str | None = None,
    prioridade: str | None = None,
    db: Session = Depends(get_db),
):
    inicio, fim = _data(data_inicio), _data(data_fim)
    dados = DemandaService.relatorio_por_status(db, inicio, fim, categoria, prioridade)
    return templates.TemplateResponse(
        request=request,
        name="relatorios/demandas_por_status.html",
        context={
            "titulo": "Demandas por status",
            "dados": dados,
            "total": sum(item["quantidade"] for item in dados),
            "data_inicio": inicio,
            "data_fim": fim,
            "categoria": categoria,
            "prioridade": prioridade,
            "categorias": CategoriaService.listar_nomes_para_filtro(db, categoria),
            "prioridades": PRIORIDADE_OPCOES,
            "query_export": _query_string(
                data_inicio=inicio, data_fim=fim, categoria=categoria, prioridade=prioridade
            ),
        },
    )


@router.get("/demandas-por-status/exportar")
def demandas_por_status_exportar(
    data_inicio: str | None = None,
    data_fim: str | None = None,
    categoria: str | None = None,
    prioridade: str | None = None,
    db: Session = Depends(get_db),
):
    dados = DemandaService.relatorio_por_status(
        db, _data(data_inicio), _data(data_fim), categoria, prioridade
    )
    linhas = [[item["rotulo"], item["quantidade"]] for item in dados]
    return _csv_response(["Status", "Quantidade"], linhas, "demandas_por_status.csv")


# ---------- P1.2 — Demandas por categoria ----------


@router.get("/demandas-por-categoria", response_class=HTMLResponse)
def demandas_por_categoria(
    request: Request,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    status: str | None = None,
    prioridade: str | None = None,
    db: Session = Depends(get_db),
):
    inicio, fim = _data(data_inicio), _data(data_fim)
    dados = DemandaService.relatorio_por_categoria(db, inicio, fim, status, prioridade)
    return templates.TemplateResponse(
        request=request,
        name="relatorios/demandas_por_categoria.html",
        context={
            "titulo": "Demandas por categoria",
            "dados": dados,
            "total": sum(item["quantidade"] for item in dados),
            "data_inicio": inicio,
            "data_fim": fim,
            "status": status,
            "prioridade": prioridade,
            "status_opcoes": DEMANDA_STATUS_OPCOES,
            "prioridades": PRIORIDADE_OPCOES,
            "query_export": _query_string(
                data_inicio=inicio, data_fim=fim, status=status, prioridade=prioridade
            ),
        },
    )


@router.get("/demandas-por-categoria/exportar")
def demandas_por_categoria_exportar(
    data_inicio: str | None = None,
    data_fim: str | None = None,
    status: str | None = None,
    prioridade: str | None = None,
    db: Session = Depends(get_db),
):
    dados = DemandaService.relatorio_por_categoria(
        db, _data(data_inicio), _data(data_fim), status, prioridade
    )
    linhas = [[item["rotulo"], item["quantidade"]] for item in dados]
    return _csv_response(["Categoria", "Quantidade"], linhas, "demandas_por_categoria.csv")


# ---------- P1.3 — Eleitores por bairro ----------


@router.get("/eleitores-por-bairro", response_class=HTMLResponse)
def eleitores_por_bairro(
    request: Request,
    cidade: str | None = None,
    db: Session = Depends(get_db),
):
    dados = EleitorService.relatorio_por_bairro(db, cidade)
    return templates.TemplateResponse(
        request=request,
        name="relatorios/eleitores_por_bairro.html",
        context={
            "titulo": "Eleitores por bairro",
            "dados": dados,
            "total": sum(item["quantidade"] for item in dados),
            "cidade": cidade,
            "cidades": EleitorService.listar_cidades(db),
            "query_export": _query_string(cidade=cidade),
        },
    )


@router.get("/eleitores-por-bairro/exportar")
def eleitores_por_bairro_exportar(cidade: str | None = None, db: Session = Depends(get_db)):
    dados = EleitorService.relatorio_por_bairro(db, cidade)
    linhas = [[item["rotulo"], item["quantidade"]] for item in dados]
    return _csv_response(["Bairro", "Quantidade"], linhas, "eleitores_por_bairro.csv")


# ---------- P1.4 — Demandas por período ----------


@router.get("/demandas-por-periodo", response_class=HTMLResponse)
def demandas_por_periodo(
    request: Request,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    status: str | None = None,
    categoria: str | None = None,
    db: Session = Depends(get_db),
):
    inicio, fim = _data(data_inicio), _data(data_fim)
    dados = DemandaService.relatorio_por_periodo(db, inicio, fim, status, categoria)
    return templates.TemplateResponse(
        request=request,
        name="relatorios/demandas_por_periodo.html",
        context={
            "titulo": "Demandas por período",
            "dados": dados,
            "total": sum(item["quantidade"] for item in dados),
            "data_inicio": inicio,
            "data_fim": fim,
            "status": status,
            "categoria": categoria,
            "status_opcoes": DEMANDA_STATUS_OPCOES,
            "categorias": CategoriaService.listar_nomes_para_filtro(db, categoria),
            "query_export": _query_string(
                data_inicio=inicio, data_fim=fim, status=status, categoria=categoria
            ),
        },
    )


@router.get("/demandas-por-periodo/exportar")
def demandas_por_periodo_exportar(
    data_inicio: str | None = None,
    data_fim: str | None = None,
    status: str | None = None,
    categoria: str | None = None,
    db: Session = Depends(get_db),
):
    dados = DemandaService.relatorio_por_periodo(
        db, _data(data_inicio), _data(data_fim), status, categoria
    )
    linhas = [[item["rotulo"], item["quantidade"]] for item in dados]
    return _csv_response(["Mês", "Quantidade"], linhas, "demandas_por_periodo.csv")


# ---------- P1.6 — Compromissos por período ----------


@router.get("/compromissos-por-periodo", response_class=HTMLResponse)
def compromissos_por_periodo(
    request: Request,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    inicio, fim = _data(data_inicio), _data(data_fim)
    compromissos = AgendaService.relatorio_por_periodo(db, inicio, fim, status)
    return templates.TemplateResponse(
        request=request,
        name="relatorios/compromissos_por_periodo.html",
        context={
            "titulo": "Compromissos por período",
            "compromissos": compromissos,
            "total": len(compromissos),
            "data_inicio": inicio,
            "data_fim": fim,
            "status": status,
            "status_opcoes": AGENDA_STATUS_OPCOES,
            "query_export": _query_string(data_inicio=inicio, data_fim=fim, status=status),
        },
    )


@router.get("/compromissos-por-periodo/exportar")
def compromissos_por_periodo_exportar(
    data_inicio: str | None = None,
    data_fim: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    compromissos = AgendaService.relatorio_por_periodo(
        db, _data(data_inicio), _data(data_fim), status
    )
    linhas = [
        [
            c.inicio.strftime("%d/%m/%Y") if c.inicio else "",
            c.inicio.strftime("%H:%M") if c.inicio else "",
            c.titulo,
            c.local or "",
            c.responsavel or "",
            c.status or "",
        ]
        for c in compromissos
    ]
    return _csv_response(
        ["Data", "Horário", "Título", "Local", "Responsável", "Status"],
        linhas,
        "compromissos_por_periodo.csv",
    )


# ---------- P1.5 — Demandas por eleitor ----------


@router.get("/demandas-por-eleitor", response_class=HTMLResponse)
def demandas_por_eleitor(
    request: Request,
    pesquisa: str = "",
    eleitor_id: int | None = None,
    db: Session = Depends(get_db),
):
    eleitor = None
    demandas: list = []
    resultados_busca: list = []

    if eleitor_id is not None:
        eleitor = EleitorService.obter_por_id(db, eleitor_id)
        if eleitor is not None:
            demandas = DemandaService.relatorio_por_eleitor(db, eleitor_id)
    elif pesquisa.strip():
        resultados_busca, _, _ = EleitorService.listar(db, pesquisa, 1)

    return templates.TemplateResponse(
        request=request,
        name="relatorios/demandas_por_eleitor.html",
        context={
            "titulo": "Demandas por eleitor",
            "pesquisa": pesquisa,
            "eleitor": eleitor,
            "demandas": demandas,
            "resultados_busca": resultados_busca,
        },
    )


@router.get("/demandas-por-eleitor/exportar")
def demandas_por_eleitor_exportar(eleitor_id: int, db: Session = Depends(get_db)):
    demandas = DemandaService.relatorio_por_eleitor(db, eleitor_id)
    linhas = [
        [
            d.titulo,
            d.categoria or "",
            d.status or "",
            d.prioridade or "",
            d.data_abertura.strftime("%d/%m/%Y") if d.data_abertura else "",
            d.prazo.strftime("%d/%m/%Y") if d.prazo else "",
        ]
        for d in demandas
    ]
    return _csv_response(
        ["Título", "Categoria", "Status", "Prioridade", "Data de abertura", "Prazo"],
        linhas,
        f"demandas_eleitor_{eleitor_id}.csv",
    )
