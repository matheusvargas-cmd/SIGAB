from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String

from app.core.database import Base

# Vocabulário do próprio schema (mesmo espírito de PERFIS_OPCOES em
# membro_gabinete.py e STATUS_OPCOES em demanda_service.py) — status da
# ASSINATURA, distinto e independente de Gabinete.ativo (controle
# administrativo do SUPERADMIN, nunca alterado por nada relacionado a
# validade/cobrança). TRIAL: período de degustação inicial, sem plano
# escolhido ainda. ATIVO: assinatura contratada (mensal ou anual). A
# validade em si nunca é um terceiro valor de status — é sempre calculada
# comparando assinatura_vencimento com a data de hoje (ver propriedade
# assinatura_vencida abaixo), então TRIAL e ATIVO podem estar dentro ou
# fora da validade.
STATUS_ASSINATURA_OPCOES = ["TRIAL", "ATIVO"]

# Preços vigentes (Fase 1 — sem gateway de pagamento ainda, ver
# app/modules/assinatura). Mesmos valores exibidos na landing page
# (app/templates/landing/index.html) — qualquer mudança de preço deve
# atualizar os dois lugares.
PLANO_OPCOES = ["MENSAL", "ANUAL"]

DIAS_TRIAL_PADRAO = 7


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

    # Controle de validade/assinatura (Fase 1) — inteiramente independente
    # de `ativo` acima: `ativo` é a chave administrativa do SUPERADMIN
    # (gabinete existe mas está desligado), enquanto os campos abaixo só
    # decidem se o gabinete pode operar por já ter (ou não) uma assinatura
    # válida. Um gabinete pode estar ativo=True e mesmo assim vencido — ou
    # ativo=False e em dia; as duas checagens não se substituem, ver
    # app/core/contexto.py:obter_contexto_atual.
    status_assinatura = Column(String(20), nullable=False, default="TRIAL")

    # None enquanto em TRIAL (ainda não escolheu plano); MENSAL ou ANUAL
    # a partir da primeira assinatura contratada (mesmo depois de vencida
    # — mantém o registro de qual era o último plano, para a página de
    # renovação já vir com a opção mais provável destacada).
    plano = Column(String(20), nullable=True)

    assinatura_inicio = Column(Date, nullable=False, default=date.today)
    assinatura_vencimento = Column(Date, nullable=False)

    @property
    def assinatura_vencida(self) -> bool:
        """Única fonte de verdade sobre "venceu ou não" — nunca um terceiro
        valor de status_assinatura armazenado no banco (que exigiria manter
        dois lugares sincronizados). Comparação simples de data: o gabinete
        continua funcionando normalmente até o fim do dia de vencimento."""
        return date.today() > self.assinatura_vencimento
