from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class Usuario(Base):
    """Credencial de login, independente de gabinete. O vínculo com um ou
    mais gabinetes — e o perfil dentro de cada um — mora em
    MembroGabinete, nunca aqui: uma pessoa pode futuramente atender mais
    de um gabinete com papéis diferentes em cada um.

    E-mail é o identificador de login (único globalmente, normalizado para
    minúsculo em AuthService/scripts de bootstrap) — CPF não é usado para
    autenticação nesta fase.
    """

    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    nome = Column(String(150), nullable=False)
    email = Column(String(150), nullable=False, unique=True, index=True)

    # Hash Argon2id (app/core/security.py) — nunca a senha em texto puro.
    senha_hash = Column(String(255), nullable=False)

    ativo = Column(Boolean, nullable=False, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)

    # Útil para auditoria de troca de senha/ativação — atualizado sempre
    # que o registro é alterado (ver AuthService/futura tela de usuários).
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
