from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class HistoricoDemanda(Base):
    """Registro de uma mudança de status de uma Demanda (ex.: "Protocolado"
    -> "Em análise"). usuario_id é quem fez a alteração — NULL quando a
    origem não tem usuário autenticado (ex.: a própria criação da demanda
    pelo futuro módulo público de Atendimento ao Cidadão).

    Fundação apenas: nenhum código nesta fase grava uma linha aqui — a
    gravação automática (a cada troca de status) fica para outro prompt."""

    __tablename__ = "historico_demandas"

    id = Column(Integer, primary_key=True)

    demanda_id = Column(Integer, ForeignKey("demandas.id"), nullable=False, index=True)
    demanda = relationship("Demanda")

    # Mesma redundância deliberada de DemandaAnexo.gabinete_id — nunca
    # gravar um gabinete_id diferente do da própria demanda.
    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=False, index=True)
    gabinete = relationship("Gabinete")

    # Nullable: alteração feita pelo atendimento público (sem login) não
    # tem usuário para registrar aqui — nunca inventar um usuário "sistema".
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    usuario = relationship("Usuario")

    # Nullable: o primeiro evento (demanda recém-criada) não tem "status
    # anterior" — só status_novo ("Protocolado").
    status_anterior = Column(String(40), nullable=True)
    status_novo = Column(String(40), nullable=False)

    observacao = Column(Text, nullable=True)

    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
