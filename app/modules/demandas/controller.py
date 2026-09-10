import json
from datetime import date, datetime
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
    FalhaExclusaoAnexoError,
)
from app.services.eleitor_service import EleitorService
from app.services.historico_demanda_service import HistoricoDemandaService
from app.services.storage_service import StorageError, obter_storage_service
from app.services.subcategoria_service import SubcategoriaService
from app.services.whatsapp_link_service import WhatsappLinkService

router = APIRouter(prefix="/demandas", tags=["Demandas"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def flash_message(
    message: str | None = None, category: str = "warning", destino: str = "/demandas"
) -> RedirectResponse:
    redirect = RedirectResponse(destino, status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", codificar_flash(message), max_age=10, httponly=True,
            path="/demandas", samesite="lax",
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/demandas", samesite="lax"
        )
    return redirect


def _destino_apos_acao(voltar: str) -> str:
    """Depois de visualizar/editar/excluir uma demanda, volta para a
    mesma lista (mesmos filtros/página/ordenação) de onde o usuário veio
    — nunca reseta para "/demandas" sem filtro, o que perderia o contexto
    de quem estava, por exemplo, na aba "Públicas" (Demanda.origem ==
    "PUBLICA"). `voltar` é sempre a query string literal da listagem de
    origem (montada em lista.html a partir de request.url.query),
    propagada como parâmetro por toda a navegação de visualizar/editar/
    excluir — nunca reconstruída aqui a partir de filtros individuais."""
    return f"/demandas?{voltar}" if voltar else "/demandas"


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
    origem: str = "",
    status: str = "",
    atrasada: bool = False,
    ordenar_por: str = "",
    ordenar_direcao: str = "asc",
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    # origem/status só são aceitos se forem exatamente um dos valores
    # reais do respectivo campo — qualquer outra coisa na query string
    # (adivinhada, digitada errado) é tratada como "sem filtro", nunca
    # como um erro. ordenar_direcao idem, restrito a "asc"/"desc".
    origem_filtro = origem if origem in ("INTERNA", "PUBLICA") else ""
    status_filtro = status if status in STATUS_OPCOES else ""
    ordenar_direcao = "desc" if ordenar_direcao == "desc" else "asc"
    hoje = date.today()
    demandas, pagina_atual, total_paginas = DemandaService.listar(
        db,
        contexto.gabinete_id,
        pesquisa,
        pagina,
        origem=origem_filtro or None,
        status=status_filtro or None,
        atrasada=atrasada,
        ordenar_por=ordenar_por or None,
        ordenar_direcao=ordenar_direcao,
    )
    # Situação "atrasada" nunca é lida do banco — sempre recalculada aqui
    # a partir da data de hoje (DemandaService.calcular_atraso), a mesma
    # regra usada pelo filtro `atrasada` acima e pelo dashboard.
    for demanda in demandas:
        demanda.dias_atraso = DemandaService.calcular_atraso(demanda, hoje)
    resposta = templates.TemplateResponse(
        request=request,
        name="demandas/lista.html",
        context={
            "titulo": "Demandas",
            "demandas": demandas,
            "pesquisa": pesquisa,
            "pagina_atual": pagina_atual,
            "total_paginas": total_paginas,
            "origem_filtro": origem_filtro,
            "status_filtro": status_filtro,
            "atrasada_filtro": atrasada,
            "ordenar_por": ordenar_por,
            "ordenar_direcao": ordenar_direcao,
            "status_opcoes": STATUS_OPCOES,
            "hoje": hoje,
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
            "hoje": date.today(),
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
    data_solicitacao: date | None = Form(None),
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
            data_solicitacao=data_solicitacao,
            usuario_id=contexto.usuario.id,
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
            data_solicitacao=data_solicitacao,
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
                "hoje": date.today(),
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


def _descricao_filtro(
    pesquisa: str, origem_filtro: str, status_filtro: str, atrasada: bool
) -> str:
    """Texto legível do filtro aplicado, exibido no cabeçalho do relatório
    impresso (app/templates/demandas/imprimir.html) — nunca a query string
    crua."""
    partes = []
    if origem_filtro == "INTERNA":
        partes.append("origem: Interna")
    elif origem_filtro == "PUBLICA":
        partes.append("origem: Pública")
    if status_filtro:
        partes.append(f"status: {status_filtro}")
    if atrasada:
        partes.append("apenas demandas atrasadas")
    if pesquisa.strip():
        partes.append(f'pesquisa: "{pesquisa.strip()}"')
    return "; ".join(partes) if partes else "Todas as demandas"


@router.get("/imprimir", response_class=HTMLResponse)
def imprimir(
    request: Request,
    pesquisa: str = "",
    origem: str = "",
    status: str = "",
    atrasada: bool = False,
    ordenar_por: str = "",
    ordenar_direcao: str = "asc",
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    # Mesmos filtros/ordenação de listar() acima, aceitos e validados da
    # mesma forma — a única diferença é chamar
    # DemandaService.listar_todos_filtrados (sem paginação) em vez de
    # DemandaService.listar, para que a impressão contenha TODO o conjunto
    # que corresponde ao filtro, nunca só a página exibida na tela.
    origem_filtro = origem if origem in ("INTERNA", "PUBLICA") else ""
    status_filtro = status if status in STATUS_OPCOES else ""
    ordenar_direcao = "desc" if ordenar_direcao == "desc" else "asc"
    hoje = date.today()
    demandas = DemandaService.listar_todos_filtrados(
        db,
        contexto.gabinete_id,
        pesquisa,
        origem=origem_filtro or None,
        status=status_filtro or None,
        atrasada=atrasada,
        ordenar_por=ordenar_por or None,
        ordenar_direcao=ordenar_direcao,
    )
    for demanda in demandas:
        demanda.dias_atraso = DemandaService.calcular_atraso(demanda, hoje)
    return templates.TemplateResponse(
        request=request,
        name="demandas/imprimir.html",
        context={
            "titulo": "Imprimir demandas",
            "demandas": demandas,
            "total": len(demandas),
            "gerado_em": datetime.now(),
            "descricao_filtro": _descricao_filtro(pesquisa, origem_filtro, status_filtro, atrasada),
        },
    )


@router.get("/{demanda_id}", response_class=HTMLResponse)
def visualizar(
    request: Request,
    demanda_id: int,
    voltar: str = "",
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.", destino=_destino_apos_acao(voltar))
    demanda.dias_atraso = DemandaService.calcular_atraso(demanda)
    eleitor = (
        EleitorService.obter_por_id(db, contexto.gabinete_id, demanda.eleitor_id)
        if demanda.eleitor_id
        else None
    )
    compromisso_retorno = AgendaService.obter_por_demanda(db, contexto.gabinete_id, demanda.id)
    # listar_todos_por_demanda_do_gabinete (e não listar_por_demanda):
    # inclui também anexos já indisponíveis, para o template poder
    # mostrar "Arquivo indisponível" em vez de simplesmente omitir o
    # anexo sem explicação — nunca usado para gerar link, isso continua
    # sendo só de abrir_anexo. Filtra por gabinete_id E demanda_id — a
    # terceira validação (a própria demanda pertence a este gabinete) já
    # aconteceu acima, em DemandaService.obter_por_id.
    anexos = DemandaAnexoService.listar_todos_por_demanda_do_gabinete(
        db, contexto.gabinete_id, demanda.id
    )
    historico = HistoricoDemandaService.listar_por_demanda(db, contexto.gabinete_id, demanda.id)

    whatsapp_link = None
    telefone_whatsapp_exibicao = None
    if eleitor is not None:
        telefone_whatsapp_exibicao = eleitor.whatsapp or eleitor.telefone
        mensagem = WhatsappLinkService.montar_mensagem_demanda(
            eleitor.nome, contexto.gabinete.nome, demanda.id, demanda.titulo, demanda.status
        )
        whatsapp_link = WhatsappLinkService.gerar_link(telefone_whatsapp_exibicao, mensagem)

    return templates.TemplateResponse(
        request=request,
        name="demandas/visualizar.html",
        context={
            "titulo": demanda.titulo,
            "demanda": demanda,
            "eleitor": eleitor,
            "compromisso_retorno": compromisso_retorno,
            "anexos": anexos,
            "historico": historico,
            "whatsapp_link": whatsapp_link,
            "telefone_whatsapp_exibicao": telefone_whatsapp_exibicao,
            "voltar": voltar,
            "voltar_url": _destino_apos_acao(voltar),
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
    voltar: str = "",
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.", destino=_destino_apos_acao(voltar))

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
            "hoje": date.today(),
            "eleitor_atual": eleitor_atual,
            "eleitor_resolvido": eleitor_resolvido,
            "obrigatorio": True,
            "acao_busca": f"/demandas/{demanda_id}/editar",
            "pesquisa_eleitor": pesquisa_eleitor,
            "resultados_busca_eleitor": resultados_busca_eleitor,
            "voltar": voltar,
            "voltar_url": _destino_apos_acao(voltar),
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
    data_solicitacao: date | None = Form(None),
    observacoes_internas: str | None = Form(None),
    voltar: str = Form(""),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.", destino=_destino_apos_acao(voltar))

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
            data_solicitacao=data_solicitacao,
            usuario_id=contexto.usuario.id,
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
            data_solicitacao=data_solicitacao,
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
                "hoje": date.today(),
                "eleitor_atual": eleitor_atual,
                "eleitor_resolvido": True,
                "obrigatorio": True,
                "acao_busca": f"/demandas/{demanda_id}/editar",
                "pesquisa_eleitor": "",
                "resultados_busca_eleitor": [],
                "erro": str(error),
                "voltar": voltar,
                "voltar_url": _destino_apos_acao(voltar),
                **_opcoes_formulario(db, contexto.gabinete_id, categoria_atual, subcategoria_atual),
            },
            status_code=400,
        )

    destino = _destino_apos_acao(voltar)
    if status_anterior != "Concluído" and demanda.status == "Concluído":
        return flash_message("Demanda concluída.", "success", destino=destino)
    return flash_message("Demanda atualizada.", "success", destino=destino)


@router.get("/{demanda_id}/excluir", response_class=HTMLResponse)
def confirmar_exclusao(
    request: Request,
    demanda_id: int,
    voltar: str = "",
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    # GET nunca exclui — só mostra a tela de confirmação. A exclusão de
    # fato só acontece no POST abaixo, depois que o usuário confirma
    # explicitamente ali.
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.", destino=_destino_apos_acao(voltar))
    quantidade_anexos = len(
        DemandaAnexoService.listar_por_demanda(db, contexto.gabinete_id, demanda.id)
    )
    return templates.TemplateResponse(
        request=request,
        name="demandas/excluir_confirmar.html",
        context={
            "titulo": "Excluir demanda",
            "demanda": demanda,
            "quantidade_anexos": quantidade_anexos,
            "voltar": voltar,
            "voltar_url": _destino_apos_acao(voltar),
        },
    )


@router.post("/{demanda_id}/excluir")
def excluir(
    demanda_id: int,
    voltar: str = Form(""),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(obter_contexto_atual),
):
    # contexto (obter_contexto_atual) já garante autenticação + vínculo
    # ativo com o gabinete; obter_por_id garante que a demanda pertence a
    # ESTE gabinete — nunca confia só no demanda_id da URL. A partir daí
    # toda a decisão (o que apagar do R2, o que apagar do banco, em que
    # ordem) é responsabilidade centralizada de DemandaService.excluir —
    # nenhuma lógica de storage/R2 aqui no controller.
    destino = _destino_apos_acao(voltar)
    demanda = DemandaService.obter_por_id(db, contexto.gabinete_id, demanda_id)
    if demanda is None:
        return flash_message("Demanda não encontrada.", destino=destino)
    try:
        DemandaService.excluir(db, demanda)
    except FalhaExclusaoAnexoError as error:
        return flash_message(str(error), "danger", destino=destino)
    return flash_message("Demanda excluída.", "success", destino=destino)
