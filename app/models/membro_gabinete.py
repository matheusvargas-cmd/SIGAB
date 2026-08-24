from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base

# Perfis iniciais avaliados no documento de arquitetura (seção 7): cobrem os
# três papéis já identificados sem inventar granularidade que ninguém pediu
# ainda. Fica aqui (não em app/services) porque é vocabulário do próprio
# schema, no mesmo espírito de STATUS_OPCOES em demanda_service.py.
PERFIS_OPCOES = ["ADMIN", "VEREADOR", "ASSESSOR"]


class MembroGabinete(Base):
    """Vínculo usuário↔gabinete — é aqui, e não em Usuario, que mora o
    perfil, porque o mesmo usuário pode pertencer a mais de um gabinete
    com um papel diferente em cada um (ex.: assessor que atende dois
    vereadores)."""

    __tablename__ = "membros_gabinete"
    __table_args__ = (
        UniqueConstraint("usuario_id", "gabinete_id", name="uq_membro_usuario_gabinete"),
    )

    id = Column(Integer, primary_key=True)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario = relationship("Usuario")

    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=False)
    gabinete = relationship("Gabinete")

    perfil = Column(String(20), nullable=False)
    ativo = Column(Boolean, nullable=False, default=True)
