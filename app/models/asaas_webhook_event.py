from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base

# Vocabulário do próprio schema (mesmo espírito de STATUS_ASSINATURA_OPCOES
# em gabinete.py) — nunca um valor livre. RECEBIDO é só o estado
# transitório entre inserir a linha e terminar o processamento (nunca
# deveria ficar assim por muito tempo). PROCESSADO/IGNORADO/DUPLICADO são
# terminais de sucesso — uma nova entrega do mesmo event_id nesses três
# estados nunca reprocessa, só responde 200 de novo. ERRO é o único
# estado que permite nova tentativa: uma entrega seguinte do mesmo
# event_id reprocessa de verdade (ver app/modules/webhooks/controller.py).
STATUS_EVENTO_OPCOES = ["RECEBIDO", "PROCESSADO", "IGNORADO", "DUPLICADO", "ERRO"]


class AsaasWebhookEvent(Base):
    """Registro de idempotência de ENTREGA dos webhooks do Asaas (POST
    /webhooks/asaas, ver app/modules/webhooks/controller.py) — distinto
    da idempotência FINANCEIRA (ver AsaasPagamentoProcessado). O Asaas
    entrega eventos "at-least-once" — o mesmo evento pode chegar mais de
    uma vez — então `event_id` (o campo `id` do payload, único por
    evento no Asaas) é gravado com UNIQUE antes de qualquer
    processamento. Uma segunda entrega do mesmo event_id só reprocessa
    de verdade se a tentativa anterior terminou em ERRO; qualquer outro
    status é definitivo. `payload` guarda o corpo bruto recebido só para
    auditoria/suporte — nunca é a fonte de verdade de nada; quem decide
    validade da assinatura continua sendo exclusivamente
    Gabinete.status_assinatura/assinatura_vencimento."""

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
