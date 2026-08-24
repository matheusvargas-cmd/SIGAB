from sqlalchemy import Column, Date, ForeignKey, Integer, String, Text

from app.core.database import Base


class Eleitor(Base):
    __tablename__ = "eleitores"

    id = Column(Integer, primary_key=True, index=True)

    # Nullable por enquanto: dado existente (local, pré multi-tenant) não
    # tem gabinete atribuído ainda. Ver documento de arquitetura, seção 8.
    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=True, index=True)

    nome = Column(String(150), nullable=False, index=True)
    apelido = Column(String(100))
    # 30 não era suficiente: dados reais do gabinete trazem mais de um
    # telefone concatenado no mesmo campo (ex. "(32) 9992-81207,  (32)
    # 9993-56940", 33 caracteres) — SQLite nunca reclamou (não aplica o
    # limite de VARCHAR), PostgreSQL rejeita a linha inteira. Achado real
    # ao testar a importação real contra Postgres nesta fase.
    telefone = Column(String(60))
    whatsapp = Column(String(60))
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
