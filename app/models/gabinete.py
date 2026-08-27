from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String

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

    # E-mail institucional do gabinete (compartilhado pela equipe) —
    # distinto do e-mail individual de login de cada Usuario. Usado hoje só
    # pelo e-mail diário (app/services/daily_email_service.py). Nullable:
    # gabinete sem e-mail configurado simplesmente não recebe o diário
    # ainda, nunca é erro.
    email_institucional = Column(String(150), nullable=True)

    # Data (America/Sao_Paulo) do último e-mail diário enviado com sucesso
    # para este gabinete — só isso, não um histórico. É a trava de
    # idempotência do DailyEmailService: só grava depois do SMTP confirmar
    # o envio, então uma tentativa que falhou no meio pode ser refeita no
    # mesmo dia sem duplicar.
    ultimo_email_diario_data = Column(Date, nullable=True)
