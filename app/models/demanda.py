from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Demanda(Base):
    __tablename__ = "demandas"

    id = Column(Integer, primary_key=True)

    eleitor_id = Column(Integer, ForeignKey("eleitores.id"), nullable=False)
    eleitor = relationship("Eleitor")

    titulo = Column(String(150), nullable=False)

    descricao = Column(Text)

    categoria = Column(String(60))

    status = Column(String(40), default="Aberta")

    secretaria = Column(String(100))

    prioridade = Column(String(30), default="Normal")

    responsavel = Column(String(150))

    data_abertura = Column(DateTime)

    prazo = Column(Date)

    data_fechamento = Column(DateTime)

    observacoes_internas = Column(Text)