from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.demanda_anexo import DemandaAnexo


class DemandaAnexoService:
    """Toda consulta aqui filtra por gabinete_id — mesma regra de
    isolamento multi-tenant do resto do sistema (ver
    app/core/contexto.py). Não basta o anexo pertencer à demanda certa:
    tem que pertencer também ao gabinete autenticado. Ver uso em
    app/modules/demandas/controller.py, que ainda revalida
    anexo.demanda_id contra a demanda já resolvida antes de gerar
    qualquer URL de leitura."""

    @staticmethod
    def listar_por_demanda(db: Session, gabinete_id: int, demanda_id: int) -> list[DemandaAnexo]:
        consulta = (
            select(DemandaAnexo)
            .where(
                DemandaAnexo.demanda_id == demanda_id,
                DemandaAnexo.gabinete_id == gabinete_id,
                DemandaAnexo.arquivo_disponivel.is_(True),
            )
            .order_by(DemandaAnexo.criado_em)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def listar_todos_por_demanda_do_gabinete(
        db: Session, gabinete_id: int, demanda_id: int
    ) -> list[DemandaAnexo]:
        """Como listar_por_demanda, mas inclui também os já marcados
        arquivo_disponivel=False — usado pela tela de visualização
        interna (app/modules/demandas/controller.py:visualizar) para o
        assessor conseguir ver que a demanda TINHA um anexo que ficou
        indisponível, em vez de esse anexo simplesmente sumir da lista
        sem explicação. Nunca usado para gerar link/URL — isso continua
        sendo responsabilidade exclusiva de abrir_anexo, que recusa
        qualquer anexo com arquivo_disponivel=False antes de sequer
        pedir uma URL temporária ao storage."""
        consulta = (
            select(DemandaAnexo)
            .where(
                DemandaAnexo.demanda_id == demanda_id,
                DemandaAnexo.gabinete_id == gabinete_id,
            )
            .order_by(DemandaAnexo.criado_em)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def listar_todos_por_demanda(db: Session, demanda_id: int) -> list[DemandaAnexo]:
        """Igual a listar_por_demanda, mas sem o filtro arquivo_disponivel
        e sem gabinete_id — uso interno restrito a
        DemandaService.excluir(), que já recebeu uma Demanda validada
        (obtida via obter_por_id, portanto já do gabinete certo) e
        precisa enxergar TODO anexo da demanda, mesmo um já marcado
        arquivo_disponivel=False, para apagar a linha de metadado."""
        consulta = (
            select(DemandaAnexo)
            .where(DemandaAnexo.demanda_id == demanda_id)
            .order_by(DemandaAnexo.criado_em)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def obter_por_id(db: Session, gabinete_id: int, anexo_id: int) -> DemandaAnexo | None:
        anexo = db.get(DemandaAnexo, anexo_id)
        if anexo is None or anexo.gabinete_id != gabinete_id:
            return None
        return anexo
