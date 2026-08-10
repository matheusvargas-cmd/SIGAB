from datetime import date, datetime, time
from math import ceil
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.agenda import Agenda
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
            termo = f"%{pesquisa.strip()}%"
            filtro = or_(
                Agenda.titulo.ilike(termo),
                Agenda.descricao.ilike(termo),
                Agenda.local.ilike(termo),
                Agenda.responsavel.ilike(termo),
                Agenda.status.ilike(termo),
                Eleitor.nome.ilike(termo),
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
