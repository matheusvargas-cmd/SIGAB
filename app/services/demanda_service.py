from datetime import date, datetime, time
from math import ceil
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.busca import normalizar
from app.models.categoria import Categoria
from app.models.demanda import Demanda
from app.models.eleitor import Eleitor
from app.models.subcategoria import Subcategoria
from app.services.agenda_service import AgendaService

POR_PAGINA = 20
TITULO_MINIMO_CARACTERES = 5

CATEGORIAS = [
    "Saúde",
    "Educação",
    "Obras",
    "Iluminação",
    "Limpeza",
    "Trânsito",
    "Esporte",
    "Assistência Social",
    "Habitação",
    "Outros",
]
STATUS_OPCOES = ["Aberta", "Em andamento", "Aguardando terceiros", "Concluída", "Cancelada"]
PRIORIDADE_OPCOES = ["Baixa", "Normal", "Alta", "Urgente"]

STATUS_FINALIZADOS = ("Concluída", "Cancelada")

_ORDEM_PRIORIDADE = case(
    (Demanda.prioridade == "Urgente", 0),
    (Demanda.prioridade == "Alta", 1),
    (Demanda.prioridade == "Normal", 2),
    (Demanda.prioridade == "Baixa", 3),
    else_=4,
)


class DemandaService:
    @staticmethod
    def listar(
        db: Session, pesquisa: str | None = None, pagina: int = 1
    ) -> tuple[list[Demanda], int, int]:
        consulta = (
            select(Demanda)
            .join(Eleitor, Demanda.eleitor_id == Eleitor.id)
            .options(joinedload(Demanda.eleitor))
        )
        consulta_total = (
            select(func.count())
            .select_from(Demanda)
            .join(Eleitor, Demanda.eleitor_id == Eleitor.id)
        )

        if pesquisa and pesquisa.strip():
            termo = f"%{normalizar(pesquisa.strip())}%"
            filtro = or_(
                func.normalizar(Eleitor.nome).like(termo),
                func.normalizar(Demanda.titulo).like(termo),
                func.normalizar(Demanda.categoria).like(termo),
                func.normalizar(Demanda.status).like(termo),
                func.normalizar(Demanda.responsavel).like(termo),
                func.normalizar(Eleitor.cidade).like(termo),
            )
            consulta = consulta.where(filtro)
            consulta_total = consulta_total.where(filtro)

        total_registros = db.scalar(consulta_total) or 0
        total_paginas = max(1, ceil(total_registros / POR_PAGINA))
        pagina_atual = min(max(1, pagina), total_paginas)

        consulta = (
            consulta.order_by(_ORDEM_PRIORIDADE, Demanda.data_abertura)
            .limit(POR_PAGINA)
            .offset((pagina_atual - 1) * POR_PAGINA)
        )
        demandas = list(db.scalars(consulta).unique().all())
        return demandas, pagina_atual, total_paginas

    @staticmethod
    def obter_por_id(db: Session, demanda_id: int) -> Demanda | None:
        return db.get(Demanda, demanda_id)

    @staticmethod
    def obter_por_ref_historico(db: Session, ref_historico: str) -> Demanda | None:
        return db.scalar(select(Demanda).where(Demanda.ref_historico == ref_historico))

    @staticmethod
    def listar_eleitores_para_selecao(db: Session) -> list[Eleitor]:
        return list(db.scalars(select(Eleitor).order_by(Eleitor.nome)).all())

    @staticmethod
    def contar_em_andamento(db: Session) -> int:
        consulta = (
            select(func.count())
            .select_from(Demanda)
            .where(Demanda.status.notin_(STATUS_FINALIZADOS))
        )
        return db.scalar(consulta) or 0

    @staticmethod
    def contar_concluidas(db: Session) -> int:
        consulta = (
            select(func.count()).select_from(Demanda).where(Demanda.status == "Concluída")
        )
        return db.scalar(consulta) or 0

    @staticmethod
    def listar_recentes(db: Session, limite: int = 5) -> list[Demanda]:
        consulta = (
            select(Demanda)
            .options(joinedload(Demanda.eleitor))
            .order_by(Demanda.data_abertura.desc())
            .limit(limite)
        )
        return list(db.scalars(consulta).unique().all())

    @staticmethod
    def relatorio_por_status(
        db: Session,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        categoria: str | None = None,
        prioridade: str | None = None,
    ) -> list[dict]:
        consulta = select(Demanda.status, func.count()).group_by(Demanda.status)
        consulta = DemandaService._aplicar_filtros_relatorio(
            consulta, data_inicio, data_fim, categoria=categoria, prioridade=prioridade
        )
        contagem = dict(db.execute(consulta).all())
        return [
            {"rotulo": status, "quantidade": contagem.get(status, 0)}
            for status in STATUS_OPCOES
        ]

    @staticmethod
    def relatorio_por_categoria(
        db: Session,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        status: str | None = None,
        prioridade: str | None = None,
    ) -> list[dict]:
        consulta = select(Demanda.categoria, func.count()).group_by(Demanda.categoria)
        consulta = DemandaService._aplicar_filtros_relatorio(
            consulta, data_inicio, data_fim, status=status, prioridade=prioridade
        )
        contagem = dict(db.execute(consulta).all())
        resultado = [
            {"rotulo": categoria, "quantidade": contagem.get(categoria, 0)}
            for categoria in CATEGORIAS
        ]
        resultado.sort(key=lambda item: item["quantidade"], reverse=True)
        return resultado

    @staticmethod
    def relatorio_por_periodo(
        db: Session,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        status: str | None = None,
        categoria: str | None = None,
    ) -> list[dict]:
        consulta = select(Demanda.data_abertura)
        consulta = DemandaService._aplicar_filtros_relatorio(
            consulta, data_inicio, data_fim, status=status, categoria=categoria
        )
        contagem: dict[str, int] = {}
        for (data_abertura,) in db.execute(consulta).all():
            if not data_abertura:
                continue
            chave = data_abertura.strftime("%Y-%m")
            contagem[chave] = contagem.get(chave, 0) + 1
        return [
            {"rotulo": chave, "quantidade": quantidade}
            for chave, quantidade in sorted(contagem.items())
        ]

    @staticmethod
    def relatorio_por_eleitor(db: Session, eleitor_id: int) -> list[Demanda]:
        consulta = (
            select(Demanda)
            .where(Demanda.eleitor_id == eleitor_id)
            .order_by(Demanda.data_abertura.desc())
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def _aplicar_filtros_relatorio(
        consulta,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        categoria: str | None = None,
        prioridade: str | None = None,
        status: str | None = None,
    ):
        if data_inicio:
            consulta = consulta.where(Demanda.data_abertura >= datetime.combine(data_inicio, time.min))
        if data_fim:
            consulta = consulta.where(Demanda.data_abertura <= datetime.combine(data_fim, time.max))
        if categoria:
            consulta = consulta.where(Demanda.categoria == categoria)
        if prioridade:
            consulta = consulta.where(Demanda.prioridade == prioridade)
        if status:
            consulta = consulta.where(Demanda.status == status)
        return consulta

    @staticmethod
    def criar(
        db: Session,
        eleitor_id: str | None,
        titulo: str,
        descricao: str | None,
        categoria_id: str | None,
        subcategoria_id: str | None,
        status: str | None,
        prioridade: str | None,
        responsavel: str | None = None,
        prazo: date | None = None,
        observacoes_internas: str | None = None,
        secretaria: str | None = None,
        ref_historico: str | None = None,
        data_abertura: datetime | None = None,
        fechar_automaticamente: bool = True,
    ) -> Demanda:
        # secretaria/ref_historico/data_abertura/fechar_automaticamente existem
        # para a importação histórica (atendimento.csv): permitem gravar a
        # data original do atendimento e desligar o fechamento automático,
        # sem alterar o comportamento do formulário normal (que não passa
        # esses argumentos).
        dados = DemandaService._validar_dados(
            db, eleitor_id, titulo, descricao, categoria_id, subcategoria_id, status, prioridade
        )
        demanda = Demanda(
            eleitor_id=dados["eleitor_id"],
            titulo=dados["titulo"],
            descricao=dados["descricao"],
            categoria=dados["categoria_nome"],
            categoria_id=dados["categoria_id"],
            subcategoria_id=dados["subcategoria_id"],
            status=dados["status"],
            prioridade=dados["prioridade"],
            responsavel=(responsavel or "").strip() or None,
            prazo=prazo,
            observacoes_internas=(observacoes_internas or "").strip() or None,
            secretaria=(secretaria or "").strip() or None,
            ref_historico=ref_historico,
            data_abertura=data_abertura or datetime.now(),
            data_fechamento=(
                datetime.now() if fechar_automaticamente and dados["status"] == "Concluída" else None
            ),
        )
        db.add(demanda)
        db.commit()
        db.refresh(demanda)
        AgendaService.sincronizar_retorno_demanda(db, demanda)
        return demanda

    @staticmethod
    def atualizar(
        db: Session,
        demanda: Demanda,
        eleitor_id: str | None,
        titulo: str,
        descricao: str | None,
        categoria_id: str | None,
        subcategoria_id: str | None,
        status: str | None,
        prioridade: str | None,
        responsavel: str | None = None,
        prazo: date | None = None,
        observacoes_internas: str | None = None,
    ) -> Demanda:
        dados = DemandaService._validar_dados(
            db, eleitor_id, titulo, descricao, categoria_id, subcategoria_id, status, prioridade
        )

        if demanda.status == "Concluída" and dados["status"] == "Aberta":
            raise ValueError("Não é possível reabrir uma demanda concluída.")

        if dados["status"] == "Concluída" and demanda.status != "Concluída":
            demanda.data_fechamento = datetime.now()
        elif dados["status"] != "Concluída" and demanda.status == "Concluída":
            demanda.data_fechamento = None

        demanda.eleitor_id = dados["eleitor_id"]
        demanda.titulo = dados["titulo"]
        demanda.descricao = dados["descricao"]
        demanda.categoria = dados["categoria_nome"]
        demanda.categoria_id = dados["categoria_id"]
        demanda.subcategoria_id = dados["subcategoria_id"]
        demanda.status = dados["status"]
        demanda.prioridade = dados["prioridade"]
        demanda.responsavel = (responsavel or "").strip() or None
        demanda.prazo = prazo
        demanda.observacoes_internas = (observacoes_internas or "").strip() or None

        db.commit()
        db.refresh(demanda)
        AgendaService.sincronizar_retorno_demanda(db, demanda)
        return demanda

    @staticmethod
    def excluir(db: Session, demanda: Demanda) -> None:
        AgendaService.excluir_compromisso_da_demanda(db, demanda.id)
        db.delete(demanda)
        db.commit()

    @staticmethod
    def _validar_dados(
        db: Session,
        eleitor_id: str | None,
        titulo: str,
        descricao: str | None,
        categoria_id: str | None,
        subcategoria_id: str | None,
        status: str | None,
        prioridade: str | None,
    ) -> dict[str, Any]:
        try:
            eleitor_id_convertido = int(eleitor_id) if eleitor_id else None
        except (TypeError, ValueError):
            eleitor_id_convertido = None

        if eleitor_id_convertido is None or db.get(Eleitor, eleitor_id_convertido) is None:
            raise ValueError("Eleitor obrigatório.")

        titulo_normalizado = (titulo or "").strip()
        if len(titulo_normalizado) < TITULO_MINIMO_CARACTERES:
            raise ValueError("Título inválido.")

        descricao_normalizada = (descricao or "").strip()
        if not descricao_normalizada:
            raise ValueError("Descrição obrigatória.")

        try:
            categoria_id_convertido = int(categoria_id) if categoria_id else None
        except (TypeError, ValueError):
            categoria_id_convertido = None

        categoria_obj = (
            db.get(Categoria, categoria_id_convertido) if categoria_id_convertido else None
        )
        if categoria_obj is None:
            raise ValueError("Categoria obrigatória.")

        subcategoria_id_convertido = None
        if subcategoria_id and subcategoria_id.strip():
            try:
                subcategoria_id_convertido = int(subcategoria_id)
            except (TypeError, ValueError):
                raise ValueError("Subcategoria inválida.")
            subcategoria_obj = db.get(Subcategoria, subcategoria_id_convertido)
            if subcategoria_obj is None or subcategoria_obj.categoria_id != categoria_obj.id:
                raise ValueError("Subcategoria não pertence à categoria selecionada.")

        if status not in STATUS_OPCOES:
            raise ValueError("Status obrigatório.")

        if prioridade not in PRIORIDADE_OPCOES:
            raise ValueError("Prioridade obrigatória.")

        return {
            "eleitor_id": eleitor_id_convertido,
            "titulo": titulo_normalizado,
            "descricao": descricao_normalizada,
            "categoria_id": categoria_obj.id,
            "categoria_nome": categoria_obj.nome,
            "subcategoria_id": subcategoria_id_convertido,
            "status": status,
            "prioridade": prioridade,
        }
