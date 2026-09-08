from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class DemandaAnexo(Base):
    """Metadado de um arquivo anexado a uma Demanda — o conteúdo binário
    nunca mora aqui nem no PostgreSQL. Armazenamento futuro: Cloudflare R2,
    via StorageService -> R2StorageAdapter (nenhum dos dois existe ainda
    nesta fase); storage_key é só a referência ao objeto no storage, que o
    adaptador saberá resolver quando existir.

    Fundação apenas: nenhum código nesta fase cria, lê ou apaga linhas
    desta tabela — isso fica para o prompt do upload."""

    __tablename__ = "demanda_anexos"

    id = Column(Integer, primary_key=True)

    demanda_id = Column(Integer, ForeignKey("demandas.id"), nullable=False, index=True)
    demanda = relationship("Demanda")

    # Redundante com demanda.gabinete_id de propósito: nunca aceitar/gravar
    # um gabinete_id diferente do da própria demanda — é o que impede um
    # anexo de atravessar o isolamento multi-tenant (a demanda já garante
    # isso hoje; repetir aqui deixa qualquer consulta a DemandaAnexo capaz
    # de filtrar por gabinete_id sem precisar de JOIN com demandas).
    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=False, index=True)
    gabinete = relationship("Gabinete")

    storage_key = Column(String(255), nullable=False)
    nome_original = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    tamanho_bytes = Column(Integer, nullable=True)

    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Regra de retenção futura (não implementada nesta fase): 60 dias após
    # a demanda ser concluída, o arquivo físico é removido do storage — o
    # registro de metadado permanece, só arquivo_disponivel vira False e
    # excluido_em grava quando isso aconteceu. Se a demanda for reaberta
    # antes da exclusão, a rotina de limpeza (futura) deve respeitar o
    # novo status antes de apagar.
    arquivo_disponivel = Column(Boolean, nullable=False, default=True)
    excluido_em = Column(DateTime, nullable=True)
