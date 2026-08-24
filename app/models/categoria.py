from sqlalchemy import Boolean, Column, ForeignKey, Integer, String

from app.core.database import Base


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True)

    # Nullable por enquanto: as categorias seed atuais são compartilhadas
    # globalmente (pré multi-tenant). Cada gabinete terá sua própria árvore
    # de categorias quando o isolamento for aplicado — ver arquitetura, seção 8.
    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=True, index=True)

    nome = Column(String(60), nullable=False)
    ativo = Column(Boolean, nullable=False, default=True)
