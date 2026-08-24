from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Agenda(Base):
    __tablename__ = "agenda"

    id = Column(Integer, primary_key=True)

    # Nullable por enquanto: dado existente (local, pré multi-tenant) não
    # tem gabinete atribuído ainda. Ver documento de arquitetura, seção 8.
    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=True, index=True)

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

    # Mesmo achado de app/models/eleitor.py: telefone de contato pode vir
    # com mais de um número concatenado nos dados reais do gabinete.
    telefone_contato = Column(String(60))

    status = Column(String(30), default="Agendado")

    ref_historico = Column(String(64))