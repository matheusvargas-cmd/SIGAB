from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class RedefinicaoSenha(Base):
    """Token de uso único para o fluxo "esqueci minha senha"
    (RedefinicaoSenhaService). Nunca guarda o token em texto puro — só o
    hash (sha256, ver o service): mesmo um vazamento do banco não permite
    redefinir a senha de ninguém sem o valor original, que só existe no
    link enviado por e-mail. usado_em marca consumo (uso único); expira_em
    é checado a cada tentativa, mesmo antes de usado_em."""

    __tablename__ = "redefinicoes_senha"

    id = Column(Integer, primary_key=True)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    usuario = relationship("Usuario")

    token_hash = Column(String(64), nullable=False, unique=True, index=True)

    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
    expira_em = Column(DateTime, nullable=False)
    usado_em = Column(DateTime, nullable=True)
