from sqlalchemy import Boolean, Column, Integer, String

from app.core.database import Base


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True)
    nome = Column(String(60), nullable=False)
    ativo = Column(Boolean, nullable=False, default=True)
