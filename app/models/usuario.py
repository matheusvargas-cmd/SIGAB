from sqlalchemy import Column, Integer, String

from app.core.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)

    nome = Column(String(100), nullable=False)

    login = Column(String(50), unique=True, nullable=False)

    senha = Column(String(255), nullable=False)