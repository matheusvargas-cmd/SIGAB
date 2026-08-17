from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Agenda(Base):
    __tablename__ = "agenda"

    id = Column(Integer, primary_key=True)

    eleitor_id = Column(Integer, ForeignKey("eleitores.id"), nullable=True)
    eleitor = relationship("Eleitor")

    demanda_id = Column(Integer, ForeignKey("demandas.id"), nullable=True)
    demanda = relationship("Demanda")

    titulo = Column(String(150), nullable=False)

    descricao = Column(Text)

    local = Column(String(150))

    inicio = Column(DateTime, nullable=False)

    fim = Column(DateTime)

    responsavel = Column(String(150))

    telefone_contato = Column(String(30))

    status = Column(String(30), default="Agendado")

    ref_historico = Column(String(64))