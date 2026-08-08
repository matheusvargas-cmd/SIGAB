from sqlalchemy import Column, Integer, String, DateTime, Text

from app.core.database import Base


class Agenda(Base):
    __tablename__ = "agenda"

    id = Column(Integer, primary_key=True)

    titulo = Column(String(150))

    descricao = Column(Text)

    local = Column(String(150))

    inicio = Column(DateTime)

    fim = Column(DateTime)