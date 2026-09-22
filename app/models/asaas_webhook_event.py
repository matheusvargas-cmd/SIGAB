from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base

# Vocabulário do próprio schema (mesmo espírito de STATUS_ASSINATURA_OPCOES
# em gabinete.py) — nunca um valor livre.
STATUS_EVENTO_OPCOES = ["RECEBIDO", "PROCESSADO", "IGNORADO", "ERRO"]


class AsaasWebhookEvent(Base):
    """Registro de idempotência dos webhooks do Asaas (POST /webhooks/asaas,
    ver app/modules/webhooks/controller.py). O Asaas entrega eventos
    "at-least-once" — o mesmo evento pode chegar mais de uma vez — então
    `event_id` (o campo `id` do payload, único por evento no Asaas) é
    gravado com UNIQUE antes de qualquer processamento: a segunda entrega
    do mesmo evento colide nessa constraint e é descartada sem reaplicar
    nenhuma regra de negócio (nunca soma dias de novo, nunca duplica
    renovação). `payload` guarda o corpo bruto recebido só para auditoria/
    suporte — nunca é a fonte de verdade de nada; quem decide validade da
    assinatura continua sendo exclusivamente Gabinete.status_assinatura/
    assinatura_vencimento."""

    __tablename__ = "asaas_webhook_events"

    id = Column(Integer, primary_key=True)

    event_id = Column(String(100), nullable=False, unique=True, index=True)
    event_type = Column(String(60), nullable=False)

    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    status = Column(String(20), nullable=False, default="RECEBIDO")

    # Corpo bruto (JSON serializado) do evento — nunca contém dado de
    # cartão (o Asaas não envia isso em webhook de Checkout/cobrança);
    # existe só para auditoria e suporte ao investigar um caso específico.
    payload = Column(Text, nullable=True)
