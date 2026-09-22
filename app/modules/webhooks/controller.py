"""Endpoint público exclusivo para Webhooks do Asaas (Fase 2). NUNCA usa
autenticação por sessão/cookie — quem chama esta rota é o Asaas, não um
usuário logado no navegador (mesmo espírito de app/modules/jobs/
controller.py, mas com o mecanismo de token específico do Asaas: header
"asaas-access-token", comparado ao ASAAS_WEBHOOK_TOKEN configurado no
painel — nunca a própria API Key).

Duas camadas de idempotência, nunca confundidas:
  - Entrega: `event_id` (esta notificação específica já chegou?) — ver
    AsaasWebhookEvent. O Asaas entrega "at-least-once" — a mesma
    notificação pode chegar mais de uma vez.
  - Financeira: `payment.id`/`checkout.id` (esta cobrança real já gerou
    uma renovação, por QUALQUER evento?) — ver
    app/services/assinatura_service.py e AsaasPagamentoProcessado.

Retentativa: um event_id cuja última tentativa terminou em ERRO É
reprocessado numa nova entrega — só PROCESSADO/IGNORADO/DUPLICADO são
terminais. Uma falha real de processamento responde um status HTTP
diferente de 200 (nunca mascarada como sucesso), exatamente para que o
Asaas reenvie automaticamente depois."""

import json
import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.asaas_webhook_event import AsaasWebhookEvent
from app.services.assinatura_service import processar_evento_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])


def _exigir_token_valido(asaas_access_token: str | None) -> None:
    if not settings.asaas_webhook_token:
        # Sem ASAAS_WEBHOOK_TOKEN configurado, a rota fica sempre fechada
        # — nunca existe um token padrão esquecido em produção.
        raise HTTPException(status_code=503, detail="Webhook não configurado.")
    if not asaas_access_token or not secrets.compare_digest(asaas_access_token, settings.asaas_webhook_token):
        raise HTTPException(status_code=401, detail="Token inválido.")


def _obter_ou_registrar_evento(
    db, event_id: str, event_type: str, payload_texto: str
) -> tuple[AsaasWebhookEvent | None, JSONResponse | None]:
    """Decide o que fazer com este event_id ANTES de qualquer
    processamento. Retorna (evento, None) quando é preciso processar
    agora (evento novo, ou uma tentativa anterior que terminou em ERRO)
    — ou (None, resposta_pronta) quando já existe um resultado terminal
    (PROCESSADO/IGNORADO/DUPLICADO) e a regra de negócio NUNCA deve
    rodar de novo."""
    existente = db.scalar(select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == event_id))
    if existente is not None and existente.status != "ERRO":
        return None, JSONResponse({"status": existente.status.lower()})
    if existente is not None:
        # status == "ERRO" — nova tentativa autorizada, reaproveita a
        # mesma linha (nunca insere outra: colidiria com o UNIQUE).
        return existente, None

    evento = AsaasWebhookEvent(
        event_id=event_id, event_type=event_type, payload=payload_texto, status="RECEBIDO"
    )
    db.add(evento)
    try:
        db.commit()
    except IntegrityError:
        # Corrida real: outra requisição inseriu o mesmo event_id entre
        # nossa consulta e este commit. Decide de novo com a linha que
        # de fato existe agora.
        db.rollback()
        concorrente = db.scalar(select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == event_id))
        if concorrente is not None and concorrente.status != "ERRO":
            return None, JSONResponse({"status": concorrente.status.lower()})
        return concorrente, None
    return evento, None


@router.post("/webhooks/asaas")
async def receber_webhook_asaas(
    request: Request,
    asaas_access_token: str | None = Header(default=None, alias="asaas-access-token"),
) -> JSONResponse:
    _exigir_token_valido(asaas_access_token)

    corpo_bruto = await request.body()
    try:
        payload = json.loads(corpo_bruto.decode("utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Corpo do webhook não é JSON válido.")

    event_id = payload.get("id")
    event_type = payload.get("event")
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Payload sem 'id'/'event'.")

    payload_texto = corpo_bruto.decode("utf-8", errors="replace")[:8000]

    with SessionLocal() as db:
        evento, resposta_pronta = _obter_ou_registrar_evento(db, event_id, event_type, payload_texto)
        if resposta_pronta is not None:
            return resposta_pronta

        try:
            status_processamento = processar_evento_webhook(db, event_type, payload, event_id)
        except Exception:
            logger.exception("Erro ao processar evento Asaas %s (event_id=%s).", event_type, event_id)
            # Desfaz qualquer mutação parcial desta tentativa (a linha do
            # evento em si já está persistida desde antes — ver
            # _obter_ou_registrar_evento — então o rollback aqui nunca
            # perde o registro de que este event_id existe).
            db.rollback()
            evento.status = "ERRO"
            db.commit()
            # Status != 2xx de propósito: é o mecanismo que o próprio
            # Asaas usa para decidir reenviar a notificação depois —
            # nunca mascarar uma falha real de processamento como 200.
            raise HTTPException(status_code=500, detail="Erro interno ao processar o evento.")

        evento.status = status_processamento
        evento.processed_at = datetime.utcnow()
        db.commit()

    return JSONResponse({"status": status_processamento.lower()})
