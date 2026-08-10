import re
from datetime import date
from math import ceil
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.demanda import Demanda
from app.models.eleitor import Eleitor

POR_PAGINA = 20
NOME_MINIMO_CARACTERES = 3


class EleitorService:
    @staticmethod
    def listar(
        db: Session, pesquisa: str | None = None, pagina: int = 1
    ) -> tuple[list[Eleitor], int, int]:
        consulta = select(Eleitor).order_by(Eleitor.nome)
        consulta_total = select(func.count()).select_from(Eleitor)

        if pesquisa and pesquisa.strip():
            termo = f"%{pesquisa.strip()}%"
            filtro = or_(
                Eleitor.nome.ilike(termo),
                Eleitor.telefone.ilike(termo),
                Eleitor.whatsapp.ilike(termo),
                Eleitor.cidade.ilike(termo),
                Eleitor.bairro.ilike(termo),
            )
            consulta = consulta.where(filtro)
            consulta_total = consulta_total.where(filtro)

        total_registros = db.scalar(consulta_total) or 0
        total_paginas = max(1, ceil(total_registros / POR_PAGINA))
        pagina_atual = min(max(1, pagina), total_paginas)

        consulta = consulta.limit(POR_PAGINA).offset((pagina_atual - 1) * POR_PAGINA)
        eleitores = list(db.scalars(consulta).all())
        return eleitores, pagina_atual, total_paginas

    @staticmethod
    def obter_por_id(db: Session, eleitor_id: int) -> Eleitor | None:
        return db.get(Eleitor, eleitor_id)

    @staticmethod
    def contar(db: Session) -> int:
        return db.scalar(select(func.count()).select_from(Eleitor)) or 0

    @staticmethod
    def listar_recentes(db: Session, limite: int = 5) -> list[Eleitor]:
        consulta = select(Eleitor).order_by(Eleitor.id.desc()).limit(limite)
        return list(db.scalars(consulta).all())

    @staticmethod
    def listar_todos(db: Session) -> list[Eleitor]:
        return list(db.scalars(select(Eleitor).order_by(Eleitor.nome)).all())

    @staticmethod
    def criar(
        db: Session,
        nome: str,
        telefone: str | None = None,
        whatsapp: str | None = None,
        nascimento: date | None = None,
        endereco: str | None = None,
        bairro: str | None = None,
        cidade: str | None = None,
        observacoes: str | None = None,
    ) -> Eleitor:
        dados = EleitorService._normalizar_dados(
            nome=nome,
            telefone=telefone,
            whatsapp=whatsapp,
            nascimento=nascimento,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
            observacoes=observacoes,
        )
        EleitorService._validar_duplicidade(db, dados["nome"], dados["telefone"])
        eleitor = Eleitor(**dados)
        db.add(eleitor)
        db.commit()
        db.refresh(eleitor)
        return eleitor

    @staticmethod
    def atualizar(
        db: Session,
        eleitor: Eleitor,
        nome: str,
        telefone: str | None = None,
        whatsapp: str | None = None,
        nascimento: date | None = None,
        endereco: str | None = None,
        bairro: str | None = None,
        cidade: str | None = None,
        observacoes: str | None = None,
    ) -> Eleitor:
        dados = EleitorService._normalizar_dados(
            nome=nome,
            telefone=telefone,
            whatsapp=whatsapp,
            nascimento=nascimento,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
            observacoes=observacoes,
        )
        EleitorService._validar_duplicidade(
            db, dados["nome"], dados["telefone"], ignorar_id=eleitor.id
        )
        for campo, valor in dados.items():
            setattr(eleitor, campo, valor)
        db.commit()
        db.refresh(eleitor)
        return eleitor

    @staticmethod
    def excluir(db: Session, eleitor: Eleitor) -> None:
        possui_demandas = db.scalar(
            select(exists().where(Demanda.eleitor_id == eleitor.id))
        )
        if possui_demandas:
            raise ValueError("Eleitor possui demandas vinculadas.")
        db.delete(eleitor)
        db.commit()

    @staticmethod
    def _normalizar_dados(**dados: Any) -> dict[str, Any]:
        nome = (dados.get("nome") or "").strip()
        if len(nome) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome inválido.")

        dados["nome"] = nome
        for campo, valor in dados.items():
            if campo != "nome" and isinstance(valor, str):
                dados[campo] = valor.strip() or None
        return dados

    @staticmethod
    def _validar_duplicidade(
        db: Session, nome: str, telefone: str | None, ignorar_id: int | None = None
    ) -> None:
        # Duplicidade só é verificada quando há telefone, pois é a combinação
        # Nome + Telefone que caracteriza o mesmo cadastro (regra da Release 0.2).
        digitos_telefone = re.sub(r"\D", "", telefone or "")
        if not digitos_telefone:
            return

        consulta = select(Eleitor).where(func.lower(Eleitor.nome) == nome.lower())
        if ignorar_id is not None:
            consulta = consulta.where(Eleitor.id != ignorar_id)

        for candidato in db.scalars(consulta):
            if re.sub(r"\D", "", candidato.telefone or "") == digitos_telefone:
                raise ValueError("Cadastro duplicado.")
