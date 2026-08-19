from datetime import date, datetime, time
from math import ceil
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.busca import normalizar
from app.models.agenda import Agenda
from app.models.demanda import Demanda
from app.models.eleitor import Eleitor

POR_PAGINA = 20
TITULO_MINIMO_CARACTERES = 5

STATUS_OPCOES = ["Agendado", "Confirmado", "Realizado", "Cancelado"]


class AgendaService:
    @staticmethod
    def listar(
        db: Session, pesquisa: str | None = None, pagina: int = 1
    ) -> tuple[list[Agenda], int, int]:
        agora = datetime.now()
        grupo_temporal = case((Agenda.inicio >= agora, 0), else_=1)

        consulta = (
            select(Agenda)
            .outerjoin(Eleitor, Agenda.eleitor_id == Eleitor.id)
            .options(joinedload(Agenda.eleitor))
        )
        consulta_total = (
            select(func.count())
            .select_from(Agenda)
            .outerjoin(Eleitor, Agenda.eleitor_id == Eleitor.id)
        )

        if pesquisa and pesquisa.strip():
            termo = f"%{normalizar(pesquisa.strip())}%"
            filtro = or_(
                func.normalizar(Agenda.titulo).like(termo),
                func.normalizar(Agenda.descricao).like(termo),
                func.normalizar(Agenda.local).like(termo),
                func.normalizar(Agenda.responsavel).like(termo),
                func.normalizar(Agenda.status).like(termo),
                func.normalizar(Eleitor.nome).like(termo),
            )
            consulta = consulta.where(filtro)
            consulta_total = consulta_total.where(filtro)

        total_registros = db.scalar(consulta_total) or 0
        total_paginas = max(1, ceil(total_registros / POR_PAGINA))
        pagina_atual = min(max(1, pagina), total_paginas)

        consulta = (
            consulta.order_by(grupo_temporal, Agenda.inicio)
            .limit(POR_PAGINA)
            .offset((pagina_atual - 1) * POR_PAGINA)
        )
        compromissos = list(db.scalars(consulta).unique().all())
        return compromissos, pagina_atual, total_paginas

    @staticmethod
    def obter_por_id(db: Session, agenda_id: int) -> Agenda | None:
        return db.get(Agenda, agenda_id)

    @staticmethod
    def listar_eleitores_para_selecao(db: Session) -> list[Eleitor]:
        return list(db.scalars(select(Eleitor).order_by(Eleitor.nome)).all())

    @staticmethod
    def contar_futuros(db: Session) -> int:
        agora = datetime.now()
        consulta = select(func.count()).select_from(Agenda).where(Agenda.inicio >= agora)
        return db.scalar(consulta) or 0

    @staticmethod
    def contar_hoje(db: Session) -> int:
        hoje = date.today()
        inicio_dia = datetime.combine(hoje, time.min)
        fim_dia = datetime.combine(hoje, time.max)
        consulta = (
            select(func.count())
            .select_from(Agenda)
            .where(Agenda.inicio >= inicio_dia)
            .where(Agenda.inicio <= fim_dia)
        )
        return db.scalar(consulta) or 0

    @staticmethod
    def listar_proximos(db: Session, limite: int = 5) -> list[Agenda]:
        agora = datetime.now()
        consulta = (
            select(Agenda)
            .where(Agenda.inicio >= agora)
            .order_by(Agenda.inicio)
            .limit(limite)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def relatorio_por_periodo(
        db: Session,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        status: str | None = None,
    ) -> list[Agenda]:
        consulta = select(Agenda).options(joinedload(Agenda.eleitor))
        if data_inicio:
            consulta = consulta.where(Agenda.inicio >= datetime.combine(data_inicio, time.min))
        if data_fim:
            consulta = consulta.where(Agenda.inicio <= datetime.combine(data_fim, time.max))
        if status:
            consulta = consulta.where(Agenda.status == status)
        consulta = consulta.order_by(Agenda.inicio)
        return list(db.scalars(consulta).unique().all())

    @staticmethod
    def criar(
        db: Session,
        titulo: str,
        descricao: str | None,
        data: date | None,
        hora_inicio: time | None,
        hora_fim: time | None,
        local: str | None,
        responsavel: str | None,
        telefone_contato: str | None,
        status: str | None,
        eleitor_id: str | None,
    ) -> Agenda:
        dados = AgendaService._validar_dados(
            db, titulo, data, hora_inicio, hora_fim, status, eleitor_id
        )
        compromisso = Agenda(
            eleitor_id=dados["eleitor_id"],
            titulo=dados["titulo"],
            descricao=(descricao or "").strip() or None,
            local=(local or "").strip() or None,
            inicio=dados["inicio"],
            fim=dados["fim"],
            responsavel=(responsavel or "").strip() or None,
            telefone_contato=(telefone_contato or "").strip() or None,
            status=dados["status"],
        )
        db.add(compromisso)
        db.commit()
        db.refresh(compromisso)
        return compromisso

    @staticmethod
    def atualizar(
        db: Session,
        compromisso: Agenda,
        titulo: str,
        descricao: str | None,
        data: date | None,
        hora_inicio: time | None,
        hora_fim: time | None,
        local: str | None,
        responsavel: str | None,
        telefone_contato: str | None,
        status: str | None,
        eleitor_id: str | None,
    ) -> Agenda:
        dados = AgendaService._validar_dados(
            db, titulo, data, hora_inicio, hora_fim, status, eleitor_id
        )
        compromisso.eleitor_id = dados["eleitor_id"]
        compromisso.titulo = dados["titulo"]
        compromisso.descricao = (descricao or "").strip() or None
        compromisso.local = (local or "").strip() or None
        compromisso.inicio = dados["inicio"]
        compromisso.fim = dados["fim"]
        compromisso.responsavel = (responsavel or "").strip() or None
        compromisso.telefone_contato = (telefone_contato or "").strip() or None
        compromisso.status = dados["status"]

        db.commit()
        db.refresh(compromisso)
        return compromisso

    @staticmethod
    def excluir(db: Session, compromisso: Agenda) -> None:
        db.delete(compromisso)
        db.commit()

    @staticmethod
    def obter_por_demanda(db: Session, demanda_id: int) -> Agenda | None:
        return db.scalar(select(Agenda).where(Agenda.demanda_id == demanda_id))

    @staticmethod
    def sincronizar_retorno_demanda(db: Session, demanda: Demanda) -> None:
        """Mantém o compromisso automático de retorno ao eleitor em sincronia
        com o eleitor/prazo da demanda. Só considera o compromisso ligado a
        esta demanda (`Agenda.demanda_id`) — nunca toca compromissos criados
        manualmente, que sempre têm `demanda_id` nulo. Idempotente: chamar
        várias vezes com os mesmos dados não cria nem altera nada além do
        necessário.
        """
        compromisso = AgendaService.obter_por_demanda(db, demanda.id)

        deve_existir = bool(demanda.eleitor_id) and demanda.prazo is not None
        if not deve_existir:
            if compromisso is not None:
                db.delete(compromisso)
                db.commit()
            return

        titulo = f"Retorno ao eleitor — {demanda.eleitor.nome}"
        descricao = f"Retorno automático referente à demanda #{demanda.id}: {demanda.titulo}"
        inicio = datetime.combine(demanda.prazo, time.min)

        if compromisso is None:
            compromisso = Agenda(
                demanda_id=demanda.id,
                eleitor_id=demanda.eleitor_id,
                titulo=titulo,
                descricao=descricao,
                inicio=inicio,
                status="Agendado",
            )
            db.add(compromisso)
        elif (
            compromisso.titulo != titulo
            or compromisso.descricao != descricao
            or compromisso.inicio != inicio
            or compromisso.eleitor_id != demanda.eleitor_id
        ):
            compromisso.titulo = titulo
            compromisso.descricao = descricao
            compromisso.inicio = inicio
            compromisso.eleitor_id = demanda.eleitor_id

        db.commit()

    @staticmethod
    def excluir_compromisso_da_demanda(db: Session, demanda_id: int) -> None:
        compromisso = AgendaService.obter_por_demanda(db, demanda_id)
        if compromisso is not None:
            db.delete(compromisso)
            db.commit()

    @staticmethod
    def obter_por_ref_historico(db: Session, ref_historico: str) -> Agenda | None:
        return db.scalar(select(Agenda).where(Agenda.ref_historico == ref_historico))

    @staticmethod
    def criar_historico(
        db: Session,
        titulo: str,
        descricao: str | None,
        local: str | None,
        telefone_contato: str | None,
        inicio: datetime,
        fim: datetime | None,
        status: str,
        ref_historico: str,
    ) -> Agenda:
        # Caminho dedicado para a importação de compromisso.csv: os dados já
        # chegam como datetime combinado (não data+hora separados) e não
        # devem passar pela regra de tamanho mínimo do título do formulário
        # (há Assuntos históricos legítimos com só 4 caracteres, ex. "Aula").
        # eleitor_id e demanda_id são sempre nulos — a importação histórica
        # nunca associa eleitor nem demanda.
        titulo_normalizado = (titulo or "").strip()
        if not titulo_normalizado:
            raise ValueError("Título ausente.")
        if status not in STATUS_OPCOES:
            raise ValueError("Status inválido.")

        compromisso = Agenda(
            eleitor_id=None,
            demanda_id=None,
            titulo=titulo_normalizado,
            descricao=(descricao or "").strip() or None,
            local=(local or "").strip() or None,
            inicio=inicio,
            fim=fim,
            telefone_contato=(telefone_contato or "").strip() or None,
            status=status,
            ref_historico=ref_historico,
        )
        db.add(compromisso)
        db.commit()
        db.refresh(compromisso)
        return compromisso

    @staticmethod
    def _validar_dados(
        db: Session,
        titulo: str,
        data: date | None,
        hora_inicio: time | None,
        hora_fim: time | None,
        status: str | None,
        eleitor_id: str | None,
    ) -> dict[str, Any]:
        titulo_normalizado = (titulo or "").strip()
        if len(titulo_normalizado) < TITULO_MINIMO_CARACTERES:
            raise ValueError("Título inválido.")

        if data is None:
            raise ValueError("Data inválida.")

        if hora_inicio is None:
            raise ValueError("Horário inválido.")

        inicio = datetime.combine(data, hora_inicio)

        fim = None
        if hora_fim is not None:
            fim = datetime.combine(data, hora_fim)
            if fim <= inicio:
                raise ValueError("O horário de término deve ser depois do horário de início.")

        if status not in STATUS_OPCOES:
            raise ValueError("Status obrigatório.")

        try:
            eleitor_id_convertido = int(eleitor_id) if eleitor_id else None
        except (TypeError, ValueError):
            raise ValueError("Eleitor inválido.")

        if eleitor_id_convertido is not None and db.get(Eleitor, eleitor_id_convertido) is None:
            raise ValueError("Eleitor inválido.")

        return {
            "titulo": titulo_normalizado,
            "inicio": inicio,
            "fim": fim,
            "status": status,
            "eleitor_id": eleitor_id_convertido,
        }
