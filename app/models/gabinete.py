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

    # Identificador público do gabinete para o futuro módulo de Atendimento
    # ao Cidadão (/cidadao/<token>) — 6 caracteres alfanuméricos, gerado
    # criptograficamente (ver GabineteService._gerar_public_token), nunca o
    # id numérico do gabinete: expor o id permitiria adivinhar/varrer
    # gabinetes sequencialmente, o token não. Não concede nenhum acesso à
    # área administrativa por si só — é só "qual gabinete", igual a uma URL
    # curta. Nenhuma rota pública é criada nesta fase; a coluna existe só
    # para já ter todo gabinete (existente e futuro) com um token estável.
    public_token = Column(String(6), nullable=False, unique=True, index=True)
