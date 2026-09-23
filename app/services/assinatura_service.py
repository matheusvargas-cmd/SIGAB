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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tempo import hoje_operacional
from app.models.asaas_pagamento_processado import AsaasPagamentoProcessado
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


def _aplicar_renovacao(gabinete: Gabinete, plano: str) -> None:
    """Só muta os atributos em memória — nunca commita por conta própria.
    Existe separada de aplicar_pagamento_confirmado() para que
    processar_evento_webhook() possa agrupar esta mutação com o INSERT
    de AsaasPagamentoProcessado num único commit atômico (ver
    processar_evento_webhook abaixo) — nunca deixar "renovação aplicada"
    e "cobrança marcada como processada" em transações separadas, o que
    abriria uma janela para reprocessar a mesma cobrança se o processo
    caísse exatamente entre as duas."""
    if plano not in PLANOS:
        raise ValueError(f"Plano inválido: {plano!r}")

    estava_vencida = gabinete.assinatura_vencida
    novo_vencimento = calcular_novo_vencimento(gabinete, plano)

    if estava_vencida:
        gabinete.assinatura_inicio = hoje_operacional()
    gabinete.assinatura_vencimento = novo_vencimento
    gabinete.status_assinatura = "ATIVO"
    gabinete.plano = plano
    logger.info(
        "Gabinete %s renovado (plano=%s, vencimento=%s, estava_vencida=%s).",
        gabinete.id,
        plano,
        novo_vencimento,
        estava_vencida,
    )


def aplicar_pagamento_confirmado(db: Session, gabinete: Gabinete, plano: str) -> None:
    """Wrapper que commita — usado por quem chama a renovação isoladamente
    (ex.: testes), fora do fluxo atômico do Webhook. Nunca altera
    gabinete.ativo nem apaga nenhum dado."""
    _aplicar_renovacao(gabinete, plano)
    db.commit()
    db.refresh(gabinete)


# Únicos eventos que efetivamente liberam/renovam um gabinete — decisão
# arquitetural pós-auditoria: CHECKOUT_PAID usa checkout.id e
# PAYMENT_CONFIRMED/PAYMENT_RECEIVED usam payment.id, identificadores de
# entidades diferentes do Asaas que não têm correlação segura entre si
# (namespaces distintos, sem um campo confirmado na documentação que
# traduza um no outro). Tentar renovar em CHECKOUT_PAID e também nos
# eventos de pagamento da mesma cobrança inicial abriria de novo a
# janela de dupla renovação — a mesma cobrança real, descrita por dois
# identificadores que a idempotência por UNIQUE nunca poderia saber que
# são "a mesma coisa". Por isso a renovação passou a depender
# EXCLUSIVAMENTE de payment.id, tanto para a cobrança inicial quanto
# para as recorrentes seguintes — nunca de checkout.id.
EVENTOS_QUE_RENOVAM = {"PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"}

# Reconhecidos, mas sem ação sobre a validade da assinatura — só existem
# aqui para o Webhook responder 200 (evento tratado) sem cair no ramo de
# "evento desconhecido". CHECKOUT_PAID confirma que a jornada de
# Checkout foi concluída (registra asaas_checkout_id para bookkeeping/
# suporte), mas nunca concede período de assinatura — quem faz isso é
# exclusivamente PAYMENT_CONFIRMED/PAYMENT_RECEIVED, acima. Mesma lógica
# para SUBSCRIPTION_CREATED (registra asaas_subscription_id, nunca
# renova) — ver _atualizar_identificadores.
EVENTOS_RECONHECIDOS_SEM_RENOVACAO = {
    "CHECKOUT_PAID",
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
    """Só muta os atributos em memória (nunca decide validade, nunca
    commita por conta própria) — guarda o id da assinatura/checkout do
    Asaas na primeira vez que aparece, para a conciliação por
    asaas_subscription_id em _resolver_gabinete acima funcionar nas
    cobranças seguintes. Quem chama decide quando commitar, para poder
    agrupar com outras mutações da mesma unidade atômica."""
    if event_type == "SUBSCRIPTION_CREATED" and entidade.get("id") and not gabinete.asaas_subscription_id:
        gabinete.asaas_subscription_id = entidade["id"]
    if event_type.startswith("CHECKOUT_") and entidade.get("id") and gabinete.asaas_checkout_id != entidade["id"]:
        gabinete.asaas_checkout_id = entidade["id"]


def _marcar_cobranca_como_processada(
    db: Session, identificador_cobranca: str, gabinete: Gabinete, event_id: str, plano: str
) -> bool:
    """Idempotência FINANCEIRA (distinta da idempotência de entrega por
    event_id) — INSERT protegido por UNIQUE em
    AsaasPagamentoProcessado.asaas_identificador_cobranca, nunca um
    "select depois insere" vulnerável a corrida: sob concorrência real
    (duas entregas de eventos diferentes para a MESMA cobrança
    processadas em paralelo), o banco garante que só uma das duas
    transações consegue commitar esse INSERT — a outra recebe
    IntegrityError e é tratada aqui como "já processada". Retorna True
    só quando esta é, de fato, a primeira vez que esta cobrança é vista."""
    db.add(
        AsaasPagamentoProcessado(
            asaas_identificador_cobranca=identificador_cobranca,
            gabinete_id=gabinete.id,
            asaas_subscription_id=gabinete.asaas_subscription_id,
            event_id=event_id,
            plano=plano,
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def processar_evento_webhook(db: Session, event_type: str, payload: dict, event_id: str) -> str:
    """Ponto único de dispatch dos eventos do Asaas — chamado só por
    POST /webhooks/asaas, depois que o token do Webhook já foi validado e
    a idempotência de ENTREGA por event_id já foi garantida (ver
    app/models/asaas_webhook_event.py). Retorna o status a gravar no
    registro do evento: nunca levanta por evento desconhecido ou sem
    externalReference reconhecível — o Webhook sempre responde 200 nesses
    casos (evento fora do que o SIGAB trata ainda), só não renova nada.

    Duas camadas de idempotência, nunca confundidas: event_id (este
    evento específico já foi entregue?) e
    AsaasPagamentoProcessado.asaas_identificador_cobranca (esta cobrança
    real — payment.id — já gerou uma renovação, através de QUALQUER
    evento de pagamento?). PAYMENT_CONFIRMED e PAYMENT_RECEIVED chegam a
    esta função como eventos diferentes (event_id diferentes) — só a
    segunda camada impede que descrevam a mesma cobrança duas vezes.
    CHECKOUT_PAID nunca chega até aqui como evento de renovação (ver
    EVENTOS_RECONHECIDOS_SEM_RENOVACAO) — checkout.id e payment.id são
    identificadores de entidades diferentes do Asaas, sem correlação
    segura entre si, então CHECKOUT_PAID só faz bookkeeping
    (asaas_checkout_id); quem renova é exclusivamente payment.id."""
    entidade = _extrair_entidade(payload)
    gabinete, plano = _resolver_gabinete(db, entidade)

    if event_type in EVENTOS_RECONHECIDOS_SEM_RENOVACAO:
        # CHECKOUT_PAID e SUBSCRIPTION_CREATED nunca renovam — só
        # registram, respectivamente, asaas_checkout_id/
        # asaas_subscription_id (bookkeeping/conciliação — ver
        # _atualizar_identificadores e _resolver_gabinete). A renovação
        # em si é exclusiva de PAYMENT_CONFIRMED/PAYMENT_RECEIVED, abaixo.
        if gabinete is not None:
            _atualizar_identificadores(db, gabinete, entidade, event_type)
            db.commit()
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

    identificador_cobranca = entidade.get("id")
    if not identificador_cobranca:
        logger.warning(
            "Evento %s sem payment.id — não é seguro renovar sem ele.",
            event_type,
        )
        return "ERRO"

    if not _marcar_cobranca_como_processada(db, identificador_cobranca, gabinete, event_id, plano):
        logger.info(
            "Cobrança %s já havia sido processada antes (idempotência financeira) — ignorando.",
            identificador_cobranca,
        )
        return "DUPLICADO"

    _atualizar_identificadores(db, gabinete, entidade, event_type)
    _aplicar_renovacao(gabinete, plano)
    # Único commit: o registro de idempotência financeira e a renovação
    # do gabinete são gravados juntos — nunca um sem o outro.
    db.commit()
    return "PROCESSADO"
