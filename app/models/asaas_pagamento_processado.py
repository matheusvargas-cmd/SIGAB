from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class AsaasPagamentoProcessado(Base):
    """Idempotência FINANCEIRA — distinta e complementar à idempotência de
    ENTREGA de AsaasWebhookEvent (event_id). O Asaas pode descrever a
    MESMA cobrança real através de eventos diferentes, cada um com seu
    próprio event_id (ex.: PAYMENT_CONFIRMED e depois PAYMENT_RECEIVED
    para a mesma cobrança) — deduplicar só por event_id não impede que
    cada um desses eventos, individualmente novo, dispare uma renovação.

    `asaas_identificador_cobranca` é sempre o `payment.id` do evento
    PAYMENT_CONFIRMED/PAYMENT_RECEIVED que efetivamente originou a
    renovação — nunca o `checkout.id` de CHECKOUT_PAID: checkout.id e
    payment.id são identificadores de entidades diferentes do Asaas,
    sem correlação segura entre si (decisão pós-auditoria — ver
    docs/05_PAGAMENTOS_ASAAS.md), então CHECKOUT_PAID nunca chega a
    inserir nada aqui, só faz bookkeeping em
    Gabinete.asaas_checkout_id. UNIQUE nesta coluna garante, com o
    próprio banco, que o mesmo payment.id nunca aplica
    `aplicar_pagamento_confirmado` mais de uma vez — inclusive sob
    concorrência (INSERT + tratamento de conflito de UNIQUE, nunca um
    "select depois insere" sem proteção)."""

    __tablename__ = "asaas_pagamentos_processados"

    id = Column(Integer, primary_key=True)

    asaas_identificador_cobranca = Column(String(64), nullable=False, unique=True, index=True)

    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=False)

    # Só para suporte/conciliação — nunca decide nada por si só.
    asaas_subscription_id = Column(String(64), nullable=True)

    # event_id do Webhook (AsaasWebhookEvent.event_id) que confirmou esta
    # renovação — auditoria de "qual entrega efetivamente processou isto
    # primeiro", nunca uma segunda fonte de verdade.
    event_id = Column(String(100), nullable=False)

    plano = Column(String(20), nullable=False)

    processado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
