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
    def obter_por_id(db: Session, gabinete_id: int, anexo_id: int) -> DemandaAnexo | None:
        anexo = db.get(DemandaAnexo, anexo_id)
        if anexo is None or anexo.gabinete_id != gabinete_id:
            return None
        return anexo
