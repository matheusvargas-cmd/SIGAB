from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class Gabinete(Base):
    """Um mandato/gabinete usando o SIGAB. Todo dado de negócio (Eleitor,
    Demanda, Agenda, Categoria, Subcategoria) pertence a um Gabinete —
    isolamento multi-tenant por coluna gabinete_id, banco compartilhado
    (ver documento de arquitetura, seção 8: isolamento por gabinete)."""

    __tablename__ = "gabinetes"

    id = Column(Integer, primary_key=True)
    nome = Column(String(150), nullable=False)

    # Nome do vereador/responsável pelo gabinete — opcional, usado pelo
    # SUPERADMIN para diferenciar gabinetes na listagem global (o nome do
    # gabinete sozinho nem sempre deixa isso claro). Não afeta nenhuma
    # regra de negócio nem isolamento multi-tenant.
    responsavel = Column(String(150), nullable=True)

    ativo = Column(Boolean, nullable=False, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
