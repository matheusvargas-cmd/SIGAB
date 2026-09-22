"""Endpoint público exclusivo para Webhooks do Asaas (Fase 2). NUNCA usa
autenticação por sessão/cookie — quem chama esta rota é o Asaas, não um
usuário logado no navegador (mesmo espírito de app/modules/jobs/
controller.py, mas com o mecanismo de token específico do Asaas: header
"asaas-access-token", comparado ao ASAAS_WEBHOOK_TOKEN configurado no
painel — nunca a própria API Key).

Idempotência é o requisito central desta rota: o Asaas entrega eventos
"at-least-once" (o mesmo evento pode chegar mais de uma vez). O campo
"id" do payload é o identificador único do evento — persistido com
UNIQUE em asaas_webhook_events antes de qualquer processamento; um
evento já registrado nunca é reprocessado, só responde 200 de novo."""

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

    with SessionLocal() as db:
        existente = db.scalar(select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == event_id))
        if existente is not None:
            # Já registrado — segunda (ou terceira...) entrega do mesmo
            # evento. Nunca reprocessa: nunca soma dias de novo, nunca
            # duplica renovação.
            return JSONResponse({"status": "ja_processado"})

        evento = AsaasWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            payload=corpo_bruto.decode("utf-8", errors="replace")[:8000],
            status="RECEBIDO",
        )
        db.add(evento)
        try:
            db.commit()
        except IntegrityError:
            # Concorrência real: duas entregas quase simultâneas do mesmo
            # evento — a constraint UNIQUE em event_id pegou o que a
            # consulta acima, por timing, não viu a tempo.
            db.rollback()
            return JSONResponse({"status": "ja_processado"})

        try:
            status_processamento = processar_evento_webhook(db, event_type, payload)
        except Exception:
            logger.exception("Erro ao processar evento Asaas %s (event_id=%s).", event_type, event_id)
            evento.status = "ERRO"
            db.commit()
            # 200 mesmo em erro interno — evita uma tempestade de
            # reentregas para um evento que, sem alteração de código, vai
            # falhar de novo; o registro em asaas_webhook_events (status
            # ERRO) fica disponível para reprocessamento manual/suporte.
            return JSONResponse({"status": "erro_interno"})

        evento.status = status_processamento
        evento.processed_at = datetime.utcnow()
        db.commit()

    return JSONResponse({"status": status_processamento.lower()})
