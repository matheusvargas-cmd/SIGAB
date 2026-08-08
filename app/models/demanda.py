from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text

from app.core.database import Base


class Demanda(Base):
    __tablename__ = "demandas"

    id = Column(Integer, primary_key=True)

    eleitor_id = Column(Integer, ForeignKey("eleitores.id"))

    titulo = Column(String(150), nullable=False)

    descricao = Column(Text)

    status = Column(String(40), default="Recebida")

    secretaria = Column(String(100))

    prioridade = Column(String(30), default="Normal")

    data_abertura = Column(DateTime)

    data_fechamento = Column(DateTime)