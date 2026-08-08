from datetime import date
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models.demanda import Demanda
from app.models.eleitor import Eleitor


class EleitorService:
    @staticmethod
    def listar(db: Session, pesquisa: str | None = None) -> list[Eleitor]:
        consulta = select(Eleitor).order_by(Eleitor.nome)
        if pesquisa and pesquisa.strip():
            termo = f"%{pesquisa.strip()}%"
            consulta = consulta.where(
                or_(
                    Eleitor.nome.ilike(termo),
                    Eleitor.telefone.ilike(termo),
                    Eleitor.whatsapp.ilike(termo),
                    Eleitor.cidade.ilike(termo),
                    Eleitor.bairro.ilike(termo),
                )
            )
        return list(db.scalars(consulta).all())

    @staticmethod
    def obter_por_id(db: Session, eleitor_id: int) -> Eleitor | None:
        return db.get(Eleitor, eleitor_id)

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
        eleitor = Eleitor(
            **EleitorService._normalizar_dados(
                nome=nome,
                telefone=telefone,
                whatsapp=whatsapp,
                nascimento=nascimento,
                endereco=endereco,
                bairro=bairro,
                cidade=cidade,
                observacoes=observacoes,
            )
        )
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
            raise ValueError("Não é possível excluir um eleitor com demandas vinculadas.")
        db.delete(eleitor)
        db.commit()

    @staticmethod
    def _normalizar_dados(**dados: Any) -> dict[str, Any]:
        nome = dados["nome"].strip()
        if not nome:
            raise ValueError("O nome é obrigatório.")

        dados["nome"] = nome
        for campo, valor in dados.items():
            if campo != "nome" and isinstance(valor, str):
                dados[campo] = valor.strip() or None
        return dados
