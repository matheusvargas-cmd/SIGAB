from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.historico_demanda import HistoricoDemanda


class HistoricoDemandaService:
    """Único ponto que grava uma linha em HistoricoDemanda — nenhum
    controller nem outro serviço deve montar esse INSERT por conta
    própria. Ver chamadas em DemandaService.criar/atualizar/excluir.

    registrar() nunca comita por conta própria: quem chama já está no
    meio de uma transação que grava a própria Demanda (criar/atualizar),
    e o histórico precisa fazer parte dessa mesma transação — mesmo
    commit, mesmo rollback. Só db.add(), nunca db.commit() aqui."""

    @staticmethod
    def registrar(
        db: Session,
        gabinete_id: int,
        demanda_id: int,
        status_novo: str,
        status_anterior: str | None = None,
        usuario_id: int | None = None,
        observacao: str | None = None,
    ) -> HistoricoDemanda:
        evento = HistoricoDemanda(
            demanda_id=demanda_id,
            gabinete_id=gabinete_id,
            usuario_id=usuario_id,
            status_anterior=status_anterior,
            status_novo=status_novo,
            observacao=observacao,
        )
        db.add(evento)
        return evento

    @staticmethod
    def listar_por_demanda(db: Session, gabinete_id: int, demanda_id: int) -> list[HistoricoDemanda]:
        # Filtra por gabinete_id E demanda_id juntos — nunca confiar só no
        # demanda_id da URL. O controller, antes de chamar isto, já
        # validou que a própria Demanda pertence a este gabinete (ver
        # app/modules/demandas/controller.py); aqui é a segunda camada,
        # que garante que nenhum evento de outro gabinete possa vazar
        # mesmo que demanda_id tenha sido adivinhado.
        consulta = (
            select(HistoricoDemanda)
            .where(
                HistoricoDemanda.demanda_id == demanda_id,
                HistoricoDemanda.gabinete_id == gabinete_id,
            )
            .order_by(HistoricoDemanda.criado_em.desc(), HistoricoDemanda.id.desc())
        )
        return list(db.scalars(consulta).all())
