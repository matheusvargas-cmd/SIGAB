"""Client HTTP isolado para a API do Asaas (Sandbox por padrão — Fase 2).

Responsabilidade única: conversar com o Asaas (autenticação, montar a
requisição, interpretar resposta/erro). Nenhuma regra de negócio de
gabinete/assinatura mora aqui — quem decide o que fazer com o resultado
é app/services/assinatura_service.py e os controllers de
app/modules/assinatura e app/modules/webhooks.

Usa urllib (biblioteca padrão) de propósito, para não adicionar uma
dependência HTTP nova (requests/httpx) só para esta integração — o
projeto já não usa nenhuma das duas.

Campos e endpoints abaixo foram conferidos na documentação oficial em
docs.asaas.com (setembro de 2026):
  - Autenticação da API: header "access_token" com a API Key
    (docs.asaas.com/docs/autenticacao).
  - "Create new checkout" (POST /v3/checkouts): billingTypes, chargeTypes
    (RECURRENT para cobrança recorrente), items (name/description/value/
    quantity — "name" é obrigatório, "description" é campo separado),
    subscription (cycle/nextDueDate), callback (successUrl/cancelUrl/
    expiredUrl), customer ou customerData, externalReference — a criação
    do Checkout NÃO é confirmação de pagamento; isso só chega depois,
    por Webhook.
  - "Create new customer" / "List customers" (POST e GET /v3/customers):
    name e cpfCnpj obrigatórios; GET aceita filtro por externalReference.
  - Webhooks: header "asaas-access-token" comparado ao authToken
    configurado no painel — nunca a própria API Key.
"""

import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlencode

from app.core.config import settings
from app.core.tempo import hoje_operacional

logger = logging.getLogger(__name__)

VERSAO_INTEGRACAO = "1.0"


class AsaasNaoConfiguradoError(Exception):
    """ASAAS_API_KEY ausente — nenhuma chamada é feita com chave vazia."""


class AsaasError(Exception):
    """Erro de comunicação com a API do Asaas (HTTP != 2xx, timeout, ou
    resposta em formato inesperado). Nunca inclui a API Key na mensagem
    nem em log — só o método e o caminho chamado."""


class AsaasService:
    TIMEOUT_SEGUNDOS = 15

    @staticmethod
    def _requisitar(metodo: str, caminho: str, corpo: dict | None = None, query: dict | None = None) -> dict:
        if not settings.asaas_api_key:
            raise AsaasNaoConfiguradoError("ASAAS_API_KEY não configurada.")

        url = f"{settings.asaas_api_url_efetiva}{caminho}"
        if query:
            url = f"{url}?{urlencode(query)}"

        dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        requisicao = urllib.request.Request(
            url,
            data=dados,
            method=metodo,
            headers={
                "access_token": settings.asaas_api_key,
                "Content-Type": "application/json",
                "User-Agent": f"Gabinete360/{VERSAO_INTEGRACAO}",
            },
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=AsaasService.TIMEOUT_SEGUNDOS) as resposta:
                corpo_resposta = resposta.read().decode("utf-8")
        except urllib.error.HTTPError as erro:
            corpo_erro = erro.read().decode("utf-8", errors="replace")
            logger.error("Asaas respondeu %s para %s %s: %s", erro.code, metodo, caminho, corpo_erro)
            raise AsaasError(f"Asaas respondeu {erro.code} para {metodo} {caminho}.") from erro
        except urllib.error.URLError as erro:
            logger.error("Falha de rede ao chamar o Asaas (%s %s): %s", metodo, caminho, erro)
            raise AsaasError(f"Falha de rede ao chamar o Asaas ({metodo} {caminho}).") from erro

        if not corpo_resposta:
            return {}
        try:
            return json.loads(corpo_resposta)
        except ValueError as erro:
            raise AsaasError("Resposta do Asaas não é JSON válido.") from erro

    @staticmethod
    def obter_ou_criar_cliente(
        external_reference: str, nome: str, cpf_cnpj: str, email: str | None = None
    ) -> str:
        """ID do cliente Asaas correspondente a external_reference —
        reaproveita se já existir (busca só por externalReference, nunca
        por nome/e-mail, que podem se repetir entre gabinetes diferentes);
        cria apenas se a busca não encontrar nada."""
        resultado = AsaasService._requisitar(
            "GET", "/customers", query={"externalReference": external_reference, "limit": 1}
        )
        existentes = resultado.get("data") or []
        if existentes:
            return existentes[0]["id"]

        criado = AsaasService._requisitar(
            "POST",
            "/customers",
            corpo={
                "name": nome,
                "cpfCnpj": cpf_cnpj,
                "email": email or None,
                "externalReference": external_reference,
            },
        )
        return criado["id"]

    @staticmethod
    def criar_checkout(
        customer_id: str,
        descricao: str,
        valor: float,
        ciclo: str,
        external_reference: str,
        success_url: str,
        cancel_url: str,
        expired_url: str,
    ) -> dict:
        """Cria um Checkout hospedado pelo Asaas com cobrança recorrente
        (chargeTypes=RECURRENT + subscription.cycle) — o pagador conclui a
        primeira cobrança na própria tela do Checkout; as cobranças
        seguintes do mesmo ciclo são geradas automaticamente pela
        assinatura que o Asaas cria a partir deste Checkout. Retorna o
        dict completo da resposta (inclui o link para redirecionar o
        pagador). Criar o Checkout NUNCA significa pagamento confirmado —
        isso só é decidido pelo Webhook (ver app/modules/webhooks)."""
        corpo = {
            # Checkout recorrente (chargeTypes=RECURRENT): confirmado no
            # Sandbox real que CREDIT_CARD é o único billingType aceito
            # para RECURRENT — o próprio Asaas rejeita PIX aqui ("O
            # método de pagamento CREDIT_CARD é o único método de
            # pagamento permitido para operações RECURRENT"; PIX exige
            # chargeTypes=DETACHED, um fluxo diferente). Mesma conclusão
            # da documentação oficial ("Checkout com Assinatura
            # (recorrente)"), que só documenta o exemplo com CREDIT_CARD.
            "billingTypes": ["CREDIT_CARD"],
            "chargeTypes": ["RECURRENT"],
            "minutesToExpire": 60,
            "callback": {
                "successUrl": success_url,
                "cancelUrl": cancel_url,
                "expiredUrl": expired_url,
            },
            # "name" é obrigatório em cada item do Checkout (erro
            # parse_error "O campo 'name' precisa ser informado." sem
            # ele) — "description" continua enviado separadamente, são
            # campos distintos aceitos pela API.
            "items": [{"name": descricao, "description": descricao, "quantity": 1, "value": valor}],
            # "customer" foi removido de propósito (nunca "customerData"):
            # o Sandbox rejeitava o Checkout porque o cadastro do
            # customer não tinha phone/address/postalCode/province/city
            # — dados que o SIGAB não coleta nem armazena hoje (nem no
            # Gabinete, nem no Usuario). Sem "customer" nem
            # "customerData" no payload, o próprio Asaas deixa o
            # pagador informar esses dados na tela hospedada do
            # Checkout (comportamento documentado pelo Asaas) — evita
            # inventar/coletar dado cadastral que o SIGAB não tem.
            # customer_id continua recebido aqui (obter_ou_criar_cliente
            # não foi removido, ver app/modules/assinatura/controller.py)
            # só não é mais enviado ao Checkout.
            "subscription": {"cycle": ciclo, "nextDueDate": hoje_operacional().isoformat()},
            "externalReference": external_reference,
        }
        return AsaasService._requisitar("POST", "/checkouts", corpo=corpo)
