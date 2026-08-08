from sqlalchemy import Column, Date, Integer, String, Text

from app.core.database import Base


class Eleitor(Base):
    __tablename__ = "eleitores"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False, index=True)
    telefone = Column(String(30))
    whatsapp = Column(String(30))
    nascimento = Column(Date)
    endereco = Column(String(255))
    bairro = Column(String(100))
    cidade = Column(String(100))
    observacoes = Column(Text)
