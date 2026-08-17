from sqlalchemy import Column, Date, Integer, String, Text

from app.core.database import Base


class Eleitor(Base):
    __tablename__ = "eleitores"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False, index=True)
    apelido = Column(String(100))
    telefone = Column(String(30))
    whatsapp = Column(String(30))
    email = Column(String(150))
    nascimento = Column(Date)
    endereco = Column(String(255))
    bairro = Column(String(100))
    cidade = Column(String(100))
    cpf = Column(String(14))
    titulo_eleitor = Column(String(12))
    zona_eleitoral = Column(String(10))
    ref_historico = Column(String(50))
    observacoes = Column(Text)
