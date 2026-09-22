"""Regra de negócio de renovação da assinatura — Fase 2 (integração de
pagamentos com Asaas). Decide só o que muda no Gabinete quando um
pagamento é confirmado; nunca decide COMO cobrar (isso é
app/services/asaas_service.py, um client HTTP sem regra de negócio).

Preserva exatamente a semântica de validade estabelecida na Fase 1:
Gabinete.status_assinatura/plano/assinatura_inicio/assinatura_vencimento
continuam a única fonte de verdade sobre acesso (ver
Gabinete.assinatura_vencida e app/core/contexto.py). `ativo` nunca é
tocado por nada aqui — é controle administrativo do SUPERADMIN,
inteiramente independente de pagamento."""

import calendar
import logging
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tempo import hoje_operacional
from app.models.gabinete import PLANO_OPCOES, Gabinete

logger = logging.getLogger(__name__)

# Preço e período de cada plano — mesmos valores exibidos em
# app/templates/landing/index.html e app/templates/assinatura/vencido.html;
# qualquer mudança de preço precisa atualizar os três lugares. "ciclo" é o
# valor exato aceito pelo campo subscription.cycle da API do Asaas
# (conferido na documentação oficial: MONTHLY/YEARLY, entre outros).
PLANOS = {
    "MENSAL": {"valor": 99.90, "ciclo": "MONTHLY", "meses": 1, "descricao": "Gabinete 360 — Plano Mensal"},
    "ANUAL": {"valor": 799.00, "ciclo": "YEARLY", "meses": 12, "descricao": "Gabinete 360 — Plano Anual"},
}
assert set(PLANOS) == set(PLANO_OPCOES)

# externalReference do Checkout/Cliente Asaas — nunca o gabinete_id da
# sessão do navegador é usado para decidir o que renovar; a única fonte
# confiável de "qual gabinete" é este identificador, gerado pelo próprio
# SIGAB no momento da criação do Checkout e devolvido pelo Asaas dentro
# do payload do Webhook (nunca aceito cru vindo do cliente).
_PADRAO_EXTERNAL_REFERENCE = re.compile(r"^gabinete-(\d+)-(MENSAL|ANUAL)$")


def montar_external_reference(gabinete_id: int, plano: str) -> str:
    return f"gabinete-{gabinete_id}-{plano}"


def extrair_referencia(external_reference: str | None) -> tuple[int, str] | None:
    """(gabinete_id, plano) a partir de um externalReference — None se o
    valor estiver ausente ou não seguir o formato que o próprio SIGAB
    gera (nunca tenta "adivinhar" um formato de terceiro)."""
    if not external_reference:
        return None
    correspondencia = _PADRAO_EXTERNAL_REFERENCE.match(external_reference)
    if not correspondencia:
        return None
    return int(correspondencia.group(1)), correspondencia.group(2)


def _somar_meses(data: date, meses: int) -> date:
    """Soma meses usando calendário real (não 30 dias fixos) — mês com
    menos dias recebe o último dia dele (ex.: 31/01 + 1 mês = 28 ou
    29/02, nunca 03/03)."""
    mes_total = data.month - 1 + meses
    ano = data.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(data.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def calcular_novo_vencimento(gabinete: Gabinete, plano: str) -> date:
    """Semântica da Fase 1, preservada: se a assinatura já venceu, o novo
    período conta a partir de hoje (fuso operacional); se ainda está
    válida, conta a partir do vencimento atual — uma renovação antecipada
    nunca perde os dias já pagos (ex.: vence 30/09, cliente paga em 25/09,
    o novo vencimento é 30/10, nunca 25/10)."""
    base = hoje_operacional() if gabinete.assinatura_vencida else gabinete.assinatura_vencimento
    return _somar_meses(base, PLANOS[plano]["meses"])


def aplicar_pagamento_confirmado(db: Session, gabinete: Gabinete, plano: str) -> None:
    """Único ponto que efetivamente libera/renova um gabinete após
    confirmação de pagamento (chamado só pelo Webhook, nunca pelas
    páginas de callback successUrl/cancelUrl/expiredUrl — ver
    app/modules/webhooks/controller.py). Nunca altera gabinete.ativo nem
    apaga nenhum dado."""
    if plano not in PLANOS:
        raise ValueError(f"Plano inválido: {plano!r}")

    estava_vencida = gabinete.assinatura_vencida
    novo_vencimento = calcular_novo_vencimento(gabinete, plano)

    if estava_vencida:
        gabinete.assinatura_inicio = hoje_operacional()
    gabinete.assinatura_vencimento = novo_vencimento
    gabinete.status_assinatura = "ATIVO"
    gabinete.plano = plano
    db.commit()
    db.refresh(gabinete)
    logger.info(
        "Gabinete %s renovado (plano=%s, vencimento=%s, estava_vencida=%s).",
        gabinete.id,
        plano,
        novo_vencimento,
        estava_vencida,
    )


# Eventos que efetivamente liberam/renovam um gabinete. CHECKOUT_PAID é a
# primeira cobrança (concluída na própria tela do Checkout);
# PAYMENT_CONFIRMED/PAYMENT_RECEIVED cobrem as cobranças seguintes da
# assinatura recorrente criada a partir daquele Checkout.
EVENTOS_QUE_RENOVAM = {"CHECKOUT_PAID", "PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"}

# Reconhecidos, mas sem ação sobre a assinatura nesta fase — só existem
# aqui para o Webhook responder 200 (evento tratado) sem cair no ramo de
# "evento desconhecido". SUBSCRIPTION_CREATED só atualiza o identificador
# de assinatura para suporte/conciliação (ver _atualizar_identificadores).
EVENTOS_RECONHECIDOS_SEM_RENOVACAO = {
    "CHECKOUT_CANCELED",
    "CHECKOUT_EXPIRED",
    "SUBSCRIPTION_CREATED",
    "PAYMENT_OVERDUE",
    "PAYMENT_DELETED",
    "PAYMENT_REFUNDED",
}


def _extrair_entidade(payload: dict) -> dict:
    return payload.get("checkout") or payload.get("payment") or payload.get("subscription") or {}


def _resolver_gabinete(db: Session, entidade: dict) -> tuple[Gabinete | None, str | None]:
    """(gabinete, plano) a partir do evento. Tenta primeiro
    externalReference (presente em Checkout e, por herança, nas
    assinaturas/cobranças criadas a partir dele — o caminho normal).
    Sem isso, cai para asaas_subscription_id já persistido no gabinete
    (cobranças recorrentes seguintes podem não repetir o
    externalReference dependendo do fluxo) — nunca aceita gabinete_id
    numérico do próprio payload, que não existe e não seria confiável."""
    referencia = extrair_referencia(entidade.get("externalReference"))
    if referencia is not None:
        gabinete_id, plano = referencia
        return db.get(Gabinete, gabinete_id), plano

    subscription_id = entidade.get("subscription") if isinstance(entidade.get("subscription"), str) else None
    if subscription_id:
        gabinete = db.scalar(select(Gabinete).where(Gabinete.asaas_subscription_id == subscription_id))
        if gabinete is not None:
            return gabinete, gabinete.plano
    return None, None


def _atualizar_identificadores(db: Session, gabinete: Gabinete, entidade: dict, event_type: str) -> None:
    """Persistência só de bookkeeping (nunca decide validade) — guarda o
    id da assinatura/checkout do Asaas na primeira vez que aparece, para
    a conciliação por asaas_subscription_id em _resolver_gabinete acima
    funcionar nas cobranças seguintes."""
    alterou = False
    if event_type == "SUBSCRIPTION_CREATED" and entidade.get("id") and not gabinete.asaas_subscription_id:
        gabinete.asaas_subscription_id = entidade["id"]
        alterou = True
    if event_type.startswith("CHECKOUT_") and entidade.get("id") and gabinete.asaas_checkout_id != entidade["id"]:
        gabinete.asaas_checkout_id = entidade["id"]
        alterou = True
    if alterou:
        db.commit()


def processar_evento_webhook(db: Session, event_type: str, payload: dict) -> str:
    """Ponto único de dispatch dos eventos do Asaas — chamado só por
    POST /webhooks/asaas, depois que o token do Webhook já foi validado e
    a idempotência por event_id já foi garantida (ver
    app/models/asaas_webhook_event.py). Retorna o status a gravar no
    registro do evento: nunca levanta por evento desconhecido ou sem
    externalReference reconhecível — o Webhook sempre responde 200 nesses
    casos (evento fora do que o SIGAB trata ainda), só não renova nada."""
    entidade = _extrair_entidade(payload)
    gabinete, plano = _resolver_gabinete(db, entidade)

    if event_type in EVENTOS_RECONHECIDOS_SEM_RENOVACAO:
        if gabinete is not None:
            _atualizar_identificadores(db, gabinete, entidade, event_type)
        return "IGNORADO"

    if event_type not in EVENTOS_QUE_RENOVAM:
        logger.info("Evento Asaas não tratado: %s", event_type)
        return "IGNORADO"

    if gabinete is None or plano not in PLANOS:
        logger.warning(
            "Evento %s não pôde ser associado a um gabinete/plano válido (externalReference=%r).",
            event_type,
            entidade.get("externalReference"),
        )
        return "ERRO"

    _atualizar_identificadores(db, gabinete, entidade, event_type)
    aplicar_pagamento_confirmado(db, gabinete, plano)
    return "PROCESSADO"
