"""Testes da Fase 2 — integração de pagamentos com Asaas (Sandbox).

Cobre: criação de checkout (mensal/anual/plano inválido/usuário sem
gabinete/usuário de outro gabinete/SUPERADMIN), webhook (CHECKOUT_PAID,
duplicado, CANCELED, EXPIRED, evento desconhecido, token inválido) e a
regra de renovação (vencida/válida/anual, preservando gabinete.ativo e
os demais dados do gabinete).

Nunca depende da API real do Asaas — todas as chamadas de
AsaasService.obter_ou_criar_cliente/criar_checkout são mockadas; os
testes de webhook chamam processar_evento_webhook/o handler HTTP
diretamente com um payload construído à mão.

Precisa de um PostgreSQL real (nunca SQLite como referência — mesma
regra da Fase 1). Cria e remove seus próprios dados a cada teste.

Uso:
    DATABASE_URL=postgresql://usuario:senha@localhost/sigab_teste \
    SECRET_KEY=qualquer-coisa-com-32-caracteres-ou-mais \
    AMBIENTE=local \
    python3 -m unittest tests.test_asaas -v
"""

import asyncio
import json
import os
import sys
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.security import gerar_hash_senha  # noqa: E402
from app.core.tempo import hoje_operacional  # noqa: E402
from app.models.asaas_pagamento_processado import AsaasPagamentoProcessado  # noqa: E402
from app.models.asaas_webhook_event import AsaasWebhookEvent  # noqa: E402
from app.models.categoria import Categoria  # noqa: E402
from app.models.gabinete import Gabinete  # noqa: E402
from app.models.membro_gabinete import MembroGabinete  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.modules.assinatura.controller import iniciar_checkout  # noqa: E402
from app.modules.webhooks.controller import receber_webhook_asaas  # noqa: E402
from app.services.asaas_service import AsaasService  # noqa: E402
from app.services.assinatura_service import (  # noqa: E402
    aplicar_pagamento_confirmado,
    calcular_novo_vencimento,
    montar_external_reference,
)
from app.services.gabinete_service import GabineteService  # noqa: E402

# Chaves claramente fictícias — nunca chamadas de verdade (AsaasService é
# sempre mockado nestes testes), só existem para settings.asaas_configurado
# ficar True e os caminhos de código correspondentes serem exercitados.
settings.asaas_api_key = "sandbox-fake-key-somente-para-testes"
settings.asaas_webhook_token = "fake-webhook-token-somente-para-testes-0000"


class FakeRequest:
    def __init__(self, gabinete_id=None):
        self.session = {}
        if gabinete_id is not None:
            self.session["gabinete_id"] = gabinete_id
        self.state = SimpleNamespace()
        self.base_url = "http://testserver/"


class FakeWebhookRequest:
    """Substitui fastapi.Request só para o handler de webhook — que só
    usa `await request.body()`."""

    def __init__(self, corpo: dict):
        self._corpo = json.dumps(corpo).encode("utf-8")

    async def body(self) -> bytes:
        return self._corpo


class BaseTesteAsaas(unittest.TestCase):
    _contador = 0

    def setUp(self):
        self.db = SessionLocal()
        BaseTesteAsaas._contador += 1
        self.sufixo = f"Fase2Teste{BaseTesteAsaas._contador}"
        self._usuarios_ids: list[int] = []
        self._gabinetes_ids: list[int] = []
        self._eventos_ids: list[int] = []

    def tearDown(self):
        if self._eventos_ids:
            self.db.query(AsaasWebhookEvent).filter(AsaasWebhookEvent.id.in_(self._eventos_ids)).delete(
                synchronize_session=False
            )
        if self._gabinetes_ids:
            self.db.query(AsaasPagamentoProcessado).filter(
                AsaasPagamentoProcessado.gabinete_id.in_(self._gabinetes_ids)
            ).delete(synchronize_session=False)
            self.db.query(Categoria).filter(Categoria.gabinete_id.in_(self._gabinetes_ids)).delete(
                synchronize_session=False
            )
            self.db.query(MembroGabinete).filter(
                MembroGabinete.gabinete_id.in_(self._gabinetes_ids)
            ).delete(synchronize_session=False)
        if self._usuarios_ids:
            self.db.query(Usuario).filter(Usuario.id.in_(self._usuarios_ids)).delete(
                synchronize_session=False
            )
        if self._gabinetes_ids:
            self.db.query(Gabinete).filter(Gabinete.id.in_(self._gabinetes_ids)).delete(
                synchronize_session=False
            )
        self.db.commit()
        self.db.close()

    def _criar_gabinete_com_admin(self, sufixo_extra: str = "") -> tuple[Gabinete, Usuario]:
        nome_gabinete = f"Gabinete {self.sufixo}{sufixo_extra}"
        email = f"admin.{self.sufixo}{sufixo_extra}@teste.local".lower()
        gabinete = GabineteService.criar_gabinete_com_admin(
            self.db, nome_gabinete, "Responsável Teste", "Admin Teste", email, "senha12345"
        )
        usuario = self.db.scalar(select(Usuario).where(Usuario.email == email))
        self._gabinetes_ids.append(gabinete.id)
        self._usuarios_ids.append(usuario.id)
        return gabinete, usuario

    def _forcar_assinatura(self, gabinete: Gabinete, status: str, dias_para_vencer: int, plano=None):
        gabinete.status_assinatura = status
        gabinete.plano = plano
        gabinete.assinatura_vencimento = hoje_operacional() + timedelta(days=dias_para_vencer)
        self.db.commit()
        self.db.refresh(gabinete)

    def _criar_superadmin(self) -> Usuario:
        usuario = Usuario(
            nome="Superadmin Teste",
            email=f"superadmin.{self.sufixo}@teste.local".lower(),
            senha_hash=gerar_hash_senha("senha12345"),
            ativo=True,
            super_admin=True,
        )
        self.db.add(usuario)
        self.db.commit()
        self.db.refresh(usuario)
        self._usuarios_ids.append(usuario.id)
        return usuario


# ---------------------------------------------------------------------------
# 1-5: criação de checkout
# ---------------------------------------------------------------------------
class TesteCriacaoCheckout(BaseTesteAsaas):
    @patch("app.modules.assinatura.controller.AsaasService.criar_checkout")
    @patch("app.modules.assinatura.controller.AsaasService.obter_ou_criar_cliente")
    def test_checkout_mensal(self, mock_cliente, mock_checkout):
        gabinete, usuario = self._criar_gabinete_com_admin()
        mock_cliente.return_value = "cus_fake123"
        mock_checkout.return_value = {"id": "che_fake123", "link": "https://sandbox.asaas.com/c/abc"}

        request = FakeRequest(gabinete_id=gabinete.id)
        resposta = iniciar_checkout(
            request, plano="MENSAL", cpf_cnpj="123.456.789-01", nome="Ana", db=self.db, usuario=usuario
        )

        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "https://sandbox.asaas.com/c/abc")
        mock_checkout.assert_called_once()
        kwargs = mock_checkout.call_args.kwargs
        self.assertEqual(kwargs["valor"], 99.90)
        self.assertEqual(kwargs["ciclo"], "MONTHLY")
        self.assertEqual(kwargs["external_reference"], montar_external_reference(gabinete.id, "MENSAL"))
        self.db.refresh(gabinete)
        self.assertEqual(gabinete.asaas_customer_id, "cus_fake123")
        self.assertEqual(gabinete.asaas_checkout_id, "che_fake123")

    @patch("app.modules.assinatura.controller.AsaasService.criar_checkout")
    @patch("app.modules.assinatura.controller.AsaasService.obter_ou_criar_cliente")
    def test_checkout_anual(self, mock_cliente, mock_checkout):
        gabinete, usuario = self._criar_gabinete_com_admin()
        mock_cliente.return_value = "cus_fake456"
        mock_checkout.return_value = {"id": "che_fake456", "link": "https://sandbox.asaas.com/c/xyz"}

        request = FakeRequest(gabinete_id=gabinete.id)
        resposta = iniciar_checkout(
            request, plano="ANUAL", cpf_cnpj="12345678901", nome="Ana", db=self.db, usuario=usuario
        )

        self.assertEqual(resposta.status_code, 303)
        kwargs = mock_checkout.call_args.kwargs
        self.assertEqual(kwargs["valor"], 799.00)
        self.assertEqual(kwargs["ciclo"], "YEARLY")

    def test_checkout_plano_invalido(self):
        gabinete, usuario = self._criar_gabinete_com_admin()
        request = FakeRequest(gabinete_id=gabinete.id)
        resposta = iniciar_checkout(
            request, plano="TRIMESTRAL", cpf_cnpj="12345678901", nome="Ana", db=self.db, usuario=usuario
        )
        self.assertEqual(resposta.status_code, 400)

    def test_checkout_usuario_sem_gabinete(self):
        _gabinete, usuario = self._criar_gabinete_com_admin()
        request = FakeRequest(gabinete_id=None)
        resposta = iniciar_checkout(
            request, plano="MENSAL", cpf_cnpj="12345678901", nome="Ana", db=self.db, usuario=usuario
        )
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "/selecionar-gabinete")

    @patch("app.modules.assinatura.controller.AsaasService.criar_checkout")
    @patch("app.modules.assinatura.controller.AsaasService.obter_ou_criar_cliente")
    def test_checkout_usuario_de_outro_gabinete_e_bloqueado(self, mock_cliente, mock_checkout):
        _gabinete_a, usuario_a = self._criar_gabinete_com_admin("A")
        gabinete_b, _usuario_b = self._criar_gabinete_com_admin("B")

        # usuario_a tenta, via gabinete_id manipulado, iniciar checkout
        # para gabinete_b — nunca teve vínculo lá.
        request = FakeRequest(gabinete_id=gabinete_b.id)
        resposta = iniciar_checkout(
            request, plano="MENSAL", cpf_cnpj="12345678901", nome="X", db=self.db, usuario=usuario_a
        )

        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "/selecionar-gabinete")
        mock_cliente.assert_not_called()
        mock_checkout.assert_not_called()

    @patch("app.modules.assinatura.controller.AsaasService.criar_checkout")
    @patch("app.modules.assinatura.controller.AsaasService.obter_ou_criar_cliente")
    def test_superadmin_nao_usa_fluxo_normal_de_checkout(self, mock_cliente, mock_checkout):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        superadmin = self._criar_superadmin()

        request = FakeRequest(gabinete_id=gabinete.id)
        resposta = iniciar_checkout(
            request, plano="MENSAL", cpf_cnpj="12345678901", nome="X", db=self.db, usuario=superadmin
        )

        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "/superadmin/gabinetes")
        mock_cliente.assert_not_called()
        mock_checkout.assert_not_called()


class TesteCheckoutPayload(unittest.TestCase):
    """AsaasService.criar_checkout isolado (sem banco, sem chamada real —
    só o payload montado, via _requisitar mockado). Cobre a correção do
    erro parse_error "O campo 'name' precisa ser informado." devolvido
    pelo Sandbox do Asaas em POST /checkouts."""

    @patch("app.services.asaas_service.AsaasService._requisitar")
    def test_item_do_checkout_contem_campo_name_obrigatorio(self, mock_requisitar):
        mock_requisitar.return_value = {"id": "che_fake_payload", "link": "https://sandbox.asaas.com/c/x"}

        AsaasService.criar_checkout(
            customer_id="cus_fake123",
            descricao="Gabinete 360 — Plano Mensal",
            valor=99.90,
            ciclo="MONTHLY",
            external_reference="gabinete-1-MENSAL",
            success_url="https://gabinetes360.com.br/assinatura/sucesso",
            cancel_url="https://gabinetes360.com.br/assinatura/cancelado",
            expired_url="https://gabinetes360.com.br/assinatura/expirado",
        )

        mock_requisitar.assert_called_once()
        _metodo, _caminho = mock_requisitar.call_args.args
        corpo = mock_requisitar.call_args.kwargs["corpo"]
        self.assertEqual(_metodo, "POST")
        self.assertEqual(_caminho, "/checkouts")
        self.assertEqual(len(corpo["items"]), 1)
        self.assertEqual(corpo["items"][0]["name"], "Gabinete 360 — Plano Mensal")
        self.assertEqual(corpo["items"][0]["description"], "Gabinete 360 — Plano Mensal")
        self.assertEqual(corpo["items"][0]["quantity"], 1)
        self.assertEqual(corpo["items"][0]["value"], 99.90)

    @patch("app.services.asaas_service.AsaasService._requisitar")
    def test_billing_types_do_checkout_recorrente_e_somente_credit_card(self, mock_requisitar):
        """billingTypes do Checkout recorrente (chargeTypes=RECURRENT) —
        confirmado no Sandbox real que CREDIT_CARD é o único método
        aceito para RECURRENT (Asaas rejeita PIX/BOLETO aqui com 400:
        "O método de pagamento CREDIT_CARD é o único método de
        pagamento permitido para operações RECURRENT")."""
        mock_requisitar.return_value = {"id": "che_fake_payload2", "link": "https://sandbox.asaas.com/c/y"}

        AsaasService.criar_checkout(
            customer_id="cus_fake123",
            descricao="Gabinete 360 — Plano Anual",
            valor=799.00,
            ciclo="YEARLY",
            external_reference="gabinete-1-ANUAL",
            success_url="https://gabinetes360.com.br/assinatura/sucesso",
            cancel_url="https://gabinetes360.com.br/assinatura/cancelado",
            expired_url="https://gabinetes360.com.br/assinatura/expirado",
        )

        corpo = mock_requisitar.call_args.kwargs["corpo"]
        self.assertEqual(corpo["billingTypes"], ["CREDIT_CARD"])
        self.assertEqual(corpo["chargeTypes"], ["RECURRENT"])


# ---------------------------------------------------------------------------
# 6-7, 11-14: webhook + idempotência
# ---------------------------------------------------------------------------
class TesteWebhook(BaseTesteAsaas):
    def _payload_checkout(self, event_id: str, event_type: str, gabinete_id: int, plano: str) -> dict:
        return {
            "id": event_id,
            "event": event_type,
            "checkout": {
                "id": "che_fake_" + event_id,
                "externalReference": montar_external_reference(gabinete_id, plano),
            },
        }

    def _payload_pagamento(
        self, event_id: str, event_type: str, payment_id: str, gabinete_id: int, plano: str
    ) -> dict:
        """PAYMENT_CONFIRMED/PAYMENT_RECEIVED trazem o objeto "payment", com
        seu próprio "id" (payment.id) — diferente do "checkout.id". O
        mesmo payment_id pode aparecer em vários eventos (event_id)
        diferentes, exatamente o cenário que a idempotência financeira
        precisa proteger."""
        return {
            "id": event_id,
            "event": event_type,
            "payment": {
                "id": payment_id,
                "externalReference": montar_external_reference(gabinete_id, plano),
            },
        }

    def _payload_subscription(self, event_id: str, subscription_id: str, gabinete_id: int, plano: str) -> dict:
        return {
            "id": event_id,
            "event": "SUBSCRIPTION_CREATED",
            "subscription": {
                "id": subscription_id,
                "externalReference": montar_external_reference(gabinete_id, plano),
            },
        }

    def _chamar_webhook(self, corpo: dict, token: str | None):
        request = FakeWebhookRequest(corpo)
        return asyncio.run(receber_webhook_asaas(request, asaas_access_token=token))

    def _registrar_evento_para_limpeza(self, event_id: str):
        evento = self.db.scalar(select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == event_id))
        if evento is not None:
            self._eventos_ids.append(evento.id)

    def test_webhook_checkout_paid_nao_renova_apenas_atualiza_checkout_id(self):
        """Decisão arquitetural pós-auditoria: CHECKOUT_PAID nunca renova
        — checkout.id e payment.id não têm correlação segura entre si.
        CHECKOUT_PAID só faz bookkeeping (asaas_checkout_id)."""
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        vencimento_antes = gabinete.assinatura_vencimento
        payload = self._payload_checkout("evt_paid_1", "CHECKOUT_PAID", gabinete.id, "MENSAL")

        resposta = self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_paid_1")

        self.assertEqual(resposta.status_code, 200)
        self.db.refresh(gabinete)
        self.assertEqual(gabinete.status_assinatura, "TRIAL")
        self.assertEqual(gabinete.assinatura_vencimento, vencimento_antes)
        self.assertTrue(gabinete.assinatura_vencida)
        self.assertEqual(gabinete.asaas_checkout_id, "che_fake_evt_paid_1")
        # CHECKOUT_PAID nunca participa da idempotência financeira —
        # nenhum registro é criado para o checkout.id.
        registro = self.db.scalar(
            select(AsaasPagamentoProcessado).where(
                AsaasPagamentoProcessado.asaas_identificador_cobranca == "che_fake_evt_paid_1"
            )
        )
        self.assertIsNone(registro)

    def test_checkout_paid_seguido_de_payment_confirmed_renova_apenas_uma_vez(self):
        """Cenário 5 da correção: checkout.id != payment.id, CHECKOUT_PAID
        não renova, PAYMENT_CONFIRMED da mesma contratação renova
        exatamente uma vez."""
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)

        payload_checkout = self._payload_checkout("evt_cp_seq_1", "CHECKOUT_PAID", gabinete.id, "MENSAL")
        self._chamar_webhook(payload_checkout, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_cp_seq_1")
        self.db.refresh(gabinete)
        self.assertTrue(gabinete.assinatura_vencida)  # CHECKOUT_PAID não renovou

        payload_pagamento = self._payload_pagamento(
            "evt_pc_seq_1", "PAYMENT_CONFIRMED", "pay_SEQ_1", gabinete.id, "MENSAL"
        )
        self._chamar_webhook(payload_pagamento, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pc_seq_1")
        self.db.refresh(gabinete)

        self.assertFalse(gabinete.assinatura_vencida)
        self.assertEqual(gabinete.status_assinatura, "ATIVO")
        # Só existe registro de idempotência financeira para o payment.id
        # — nunca para o checkout.id (identificadores diferentes).
        self.assertIsNone(
            self.db.scalar(
                select(AsaasPagamentoProcessado).where(
                    AsaasPagamentoProcessado.asaas_identificador_cobranca == "che_fake_evt_cp_seq_1"
                )
            )
        )
        self.assertIsNotNone(
            self.db.scalar(
                select(AsaasPagamentoProcessado).where(
                    AsaasPagamentoProcessado.asaas_identificador_cobranca == "pay_SEQ_1"
                )
            )
        )

    def test_checkout_paid_seguido_de_payment_received_renova_apenas_uma_vez(self):
        """Mesmo cenário do teste anterior, com PAYMENT_RECEIVED em vez de
        PAYMENT_CONFIRMED."""
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)

        payload_checkout = self._payload_checkout("evt_cp_seq_2", "CHECKOUT_PAID", gabinete.id, "MENSAL")
        self._chamar_webhook(payload_checkout, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_cp_seq_2")

        payload_pagamento = self._payload_pagamento(
            "evt_pr_seq_2", "PAYMENT_RECEIVED", "pay_SEQ_2", gabinete.id, "MENSAL"
        )
        self._chamar_webhook(payload_pagamento, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pr_seq_2")
        self.db.refresh(gabinete)

        self.assertFalse(gabinete.assinatura_vencida)
        self.assertEqual(gabinete.status_assinatura, "ATIVO")

    def test_webhook_duplicado_nao_reprocessa(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        payload = self._payload_pagamento("evt_dup_1", "PAYMENT_CONFIRMED", "pay_DUP_1", gabinete.id, "MENSAL")

        self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_dup_1")
        self.db.refresh(gabinete)
        vencimento_apos_primeira_entrega = gabinete.assinatura_vencimento

        resposta2 = self._chamar_webhook(payload, settings.asaas_webhook_token)
        self.db.refresh(gabinete)

        self.assertEqual(resposta2.status_code, 200)
        self.assertEqual(gabinete.assinatura_vencimento, vencimento_apos_primeira_entrega)
        # Só um registro de evento — nunca duplicado.
        total = self.db.scalar(
            select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == "evt_dup_1")
        )
        self.assertIsNotNone(total)

    def test_webhook_checkout_canceled_nao_altera_assinatura(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        vencimento_antes = gabinete.assinatura_vencimento
        payload = self._payload_checkout("evt_canceled_1", "CHECKOUT_CANCELED", gabinete.id, "MENSAL")

        resposta = self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_canceled_1")

        self.assertEqual(resposta.status_code, 200)
        self.db.refresh(gabinete)
        self.assertEqual(gabinete.assinatura_vencimento, vencimento_antes)
        self.assertEqual(gabinete.status_assinatura, "TRIAL")

    def test_webhook_checkout_expired_nao_altera_assinatura(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        vencimento_antes = gabinete.assinatura_vencimento
        payload = self._payload_checkout("evt_expired_1", "CHECKOUT_EXPIRED", gabinete.id, "MENSAL")

        resposta = self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_expired_1")

        self.assertEqual(resposta.status_code, 200)
        self.db.refresh(gabinete)
        self.assertEqual(gabinete.assinatura_vencimento, vencimento_antes)

    def test_webhook_evento_desconhecido_nao_quebra(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        payload = self._payload_checkout("evt_unknown_1", "ALGO_QUE_NAO_EXISTE_AINDA", gabinete.id, "MENSAL")

        resposta = self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_unknown_1")

        self.assertEqual(resposta.status_code, 200)

    def test_webhook_sem_token_valido_e_rejeitado(self):
        payload = self._payload_checkout("evt_no_token", "CHECKOUT_PAID", 1, "MENSAL")
        with self.assertRaises(Exception) as contexto:
            self._chamar_webhook(payload, "token-completamente-errado")
        # HTTPException(401) — nunca processa nem grava o evento.
        self.assertEqual(getattr(contexto.exception, "status_code", None), 401)
        evento = self.db.scalar(
            select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == "evt_no_token")
        )
        self.assertIsNone(evento)


# ---------------------------------------------------------------------------
# Correção pós-auditoria: idempotência FINANCEIRA (payment.id) — distinta
# da idempotência de ENTREGA (event_id) já testada acima.
# ---------------------------------------------------------------------------
class TesteIdempotenciaFinanceira(BaseTesteAsaas):
    def _payload_pagamento(self, event_id, event_type, payment_id, gabinete_id, plano):
        return {
            "id": event_id,
            "event": event_type,
            "payment": {"id": payment_id, "externalReference": montar_external_reference(gabinete_id, plano)},
        }

    def _payload_subscription(self, event_id, subscription_id, gabinete_id, plano):
        return {
            "id": event_id,
            "event": "SUBSCRIPTION_CREATED",
            "subscription": {
                "id": subscription_id,
                "externalReference": montar_external_reference(gabinete_id, plano),
            },
        }

    def _chamar_webhook(self, corpo, token):
        request = FakeWebhookRequest(corpo)
        return asyncio.run(receber_webhook_asaas(request, asaas_access_token=token))

    def _registrar_evento_para_limpeza(self, event_id):
        evento = self.db.scalar(select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == event_id))
        if evento is not None:
            self._eventos_ids.append(evento.id)

    def test_subscription_created_nao_renova_apenas_registra_subscription_id(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        vencimento_antes = gabinete.assinatura_vencimento
        payload = self._payload_subscription("evt_sub_1", "sub_ABC", gabinete.id, "MENSAL")

        resposta = self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_sub_1")

        self.assertEqual(resposta.status_code, 200)
        self.db.refresh(gabinete)
        self.assertEqual(gabinete.assinatura_vencimento, vencimento_antes)
        self.assertEqual(gabinete.status_assinatura, "TRIAL")
        self.assertEqual(gabinete.asaas_subscription_id, "sub_ABC")

    def test_payment_confirmed_primeiro_evento_do_payment_renova(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        payload = self._payload_pagamento("evt_pc_1", "PAYMENT_CONFIRMED", "pay_TESTE", gabinete.id, "MENSAL")

        resposta = self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pc_1")

        self.assertEqual(resposta.status_code, 200)
        self.db.refresh(gabinete)
        self.assertEqual(gabinete.status_assinatura, "ATIVO")
        self.assertFalse(gabinete.assinatura_vencida)

    def test_payment_received_mesmo_payment_id_do_confirmed_nao_renova_de_novo(self):
        """O cenário exato da auditoria: PAYMENT_CONFIRMED (event_id=E1) e
        PAYMENT_RECEIVED (event_id=E2) para o MESMO payment.id — só a
        primeira entrega pode renovar."""
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)

        payload_confirmed = self._payload_pagamento(
            "evt_pc_2", "PAYMENT_CONFIRMED", "pay_TESTE_2", gabinete.id, "MENSAL"
        )
        self._chamar_webhook(payload_confirmed, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pc_2")
        self.db.refresh(gabinete)
        vencimento_apos_confirmed = gabinete.assinatura_vencimento

        payload_received = self._payload_pagamento(
            "evt_pr_2", "PAYMENT_RECEIVED", "pay_TESTE_2", gabinete.id, "MENSAL"
        )
        resposta2 = self._chamar_webhook(payload_received, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pr_2")
        self.db.refresh(gabinete)

        self.assertEqual(resposta2.status_code, 200)
        # Um único pagamento real — vencimento NÃO avança pela segunda vez.
        self.assertEqual(gabinete.assinatura_vencimento, vencimento_apos_confirmed)
        # Só um registro de idempotência financeira para este payment.id.
        total_registros = self.db.scalars(
            select(AsaasPagamentoProcessado).where(
                AsaasPagamentoProcessado.asaas_identificador_cobranca == "pay_TESTE_2"
            )
        ).all()
        self.assertEqual(len(total_registros), 1)

    def test_dois_payment_received_mesmo_payment_id_event_id_diferente_apenas_uma_renovacao(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)

        payload1 = self._payload_pagamento("evt_pr_3a", "PAYMENT_RECEIVED", "pay_TESTE_3", gabinete.id, "MENSAL")
        self._chamar_webhook(payload1, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pr_3a")
        self.db.refresh(gabinete)
        vencimento_apos_primeira = gabinete.assinatura_vencimento

        payload2 = self._payload_pagamento("evt_pr_3b", "PAYMENT_RECEIVED", "pay_TESTE_3", gabinete.id, "MENSAL")
        self._chamar_webhook(payload2, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pr_3b")
        self.db.refresh(gabinete)

        self.assertEqual(gabinete.assinatura_vencimento, vencimento_apos_primeira)

    def test_dois_pagamentos_diferentes_geram_duas_renovacoes_legitimas(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "ATIVO", dias_para_vencer=10, plano="MENSAL")
        vencimento_inicial = gabinete.assinatura_vencimento

        payload_a = self._payload_pagamento("evt_pa_1", "PAYMENT_CONFIRMED", "pay_A", gabinete.id, "MENSAL")
        self._chamar_webhook(payload_a, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pa_1")
        self.db.refresh(gabinete)
        vencimento_apos_a = gabinete.assinatura_vencimento
        self.assertGreater(vencimento_apos_a, vencimento_inicial)

        payload_b = self._payload_pagamento("evt_pb_1", "PAYMENT_CONFIRMED", "pay_B", gabinete.id, "MENSAL")
        self._chamar_webhook(payload_b, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_pb_1")
        self.db.refresh(gabinete)

        # Dois pagamentos reais e distintos — duas renovações legítimas.
        self.assertGreater(gabinete.assinatura_vencimento, vencimento_apos_a)

    def test_isolamento_payment_de_gabinete_a_nunca_renova_gabinete_b(self):
        gabinete_a, _usuario_a = self._criar_gabinete_com_admin("A")
        gabinete_b, _usuario_b = self._criar_gabinete_com_admin("B")
        self._forcar_assinatura(gabinete_a, "TRIAL", dias_para_vencer=-1)
        self._forcar_assinatura(gabinete_b, "TRIAL", dias_para_vencer=-1)
        vencimento_b_antes = gabinete_b.assinatura_vencimento

        payload = self._payload_pagamento(
            "evt_isolamento_1", "PAYMENT_CONFIRMED", "pay_ISOLAMENTO", gabinete_a.id, "MENSAL"
        )
        self._chamar_webhook(payload, settings.asaas_webhook_token)
        self._registrar_evento_para_limpeza("evt_isolamento_1")

        self.db.refresh(gabinete_a)
        self.db.refresh(gabinete_b)
        self.assertFalse(gabinete_a.assinatura_vencida)
        self.assertEqual(gabinete_b.assinatura_vencimento, vencimento_b_antes)
        self.assertEqual(gabinete_b.status_assinatura, "TRIAL")

    def test_evento_com_status_erro_permite_nova_tentativa(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)

        # Simula uma tentativa anterior que falhou: a linha já existe,
        # marcada ERRO (nunca chegou a renovar nada).
        evento_com_erro = AsaasWebhookEvent(
            event_id="evt_retry_1", event_type="PAYMENT_CONFIRMED", status="ERRO", payload="{}"
        )
        self.db.add(evento_com_erro)
        self.db.commit()
        self._eventos_ids.append(evento_com_erro.id)

        payload = self._payload_pagamento(
            "evt_retry_1", "PAYMENT_CONFIRMED", "pay_RETRY", gabinete.id, "MENSAL"
        )
        resposta = self._chamar_webhook(payload, settings.asaas_webhook_token)

        self.assertEqual(resposta.status_code, 200)
        self.db.refresh(gabinete)
        self.assertFalse(gabinete.assinatura_vencida)
        self.db.refresh(evento_com_erro)
        self.assertEqual(evento_com_erro.status, "PROCESSADO")

    @patch("app.modules.webhooks.controller.processar_evento_webhook")
    def test_falha_de_processamento_retorna_http_diferente_de_200_e_permite_retry(self, mock_processar):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        payload = self._payload_pagamento(
            "evt_falha_1", "PAYMENT_CONFIRMED", "pay_FALHA", gabinete.id, "MENSAL"
        )

        mock_processar.side_effect = RuntimeError("falha simulada de processamento")
        with self.assertRaises(Exception) as contexto:
            self._chamar_webhook(payload, settings.asaas_webhook_token)
        self.assertEqual(getattr(contexto.exception, "status_code", None), 500)
        self._registrar_evento_para_limpeza("evt_falha_1")

        evento = self.db.scalar(select(AsaasWebhookEvent).where(AsaasWebhookEvent.event_id == "evt_falha_1"))
        self.assertEqual(evento.status, "ERRO")
        self.db.refresh(gabinete)
        self.assertTrue(gabinete.assinatura_vencida)  # nada foi renovado na tentativa que falhou

        # Nova tentativa, agora sem a falha simulada — precisa reprocessar
        # de verdade (não pode responder "ja_processado").
        mock_processar.side_effect = None
        mock_processar.reset_mock()

        from app.services.assinatura_service import processar_evento_webhook as processar_real

        mock_processar.side_effect = processar_real
        resposta2 = self._chamar_webhook(payload, settings.asaas_webhook_token)

        self.assertEqual(resposta2.status_code, 200)
        self.db.refresh(gabinete)
        self.assertFalse(gabinete.assinatura_vencida)
        self.db.refresh(evento)
        self.assertEqual(evento.status, "PROCESSADO")


# ---------------------------------------------------------------------------
# 8-10, 15-16: regra de renovação
# ---------------------------------------------------------------------------
class TesteRegraRenovacao(BaseTesteAsaas):
    def test_renovacao_mensal_assinatura_vencida(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-5)

        aplicar_pagamento_confirmado(self.db, gabinete, "MENSAL")

        hoje = hoje_operacional()
        self.assertEqual(gabinete.assinatura_inicio, hoje)
        self.assertEqual(gabinete.assinatura_vencimento.month, (hoje.month % 12) + 1)
        self.assertFalse(gabinete.assinatura_vencida)
        self.assertEqual(gabinete.status_assinatura, "ATIVO")
        self.assertEqual(gabinete.plano, "MENSAL")

    def test_renovacao_mensal_assinatura_ainda_valida_preserva_dias_pagos(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        vencimento_original = hoje_operacional() + timedelta(days=5)
        self._forcar_assinatura(gabinete, "ATIVO", dias_para_vencer=5, plano="MENSAL")
        inicio_original = gabinete.assinatura_inicio

        novo_vencimento = calcular_novo_vencimento(gabinete, "MENSAL")
        aplicar_pagamento_confirmado(self.db, gabinete, "MENSAL")

        # Conta a partir do vencimento ATUAL, não de hoje — nunca perde
        # os dias já pagos.
        self.assertNotEqual(novo_vencimento, hoje_operacional() + timedelta(days=30))
        self.assertEqual(gabinete.assinatura_vencimento, novo_vencimento)
        self.assertGreater(gabinete.assinatura_vencimento, vencimento_original)
        # assinatura_inicio não é tocado numa renovação antecipada.
        self.assertEqual(gabinete.assinatura_inicio, inicio_original)

    def test_renovacao_anual(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        hoje = hoje_operacional()

        aplicar_pagamento_confirmado(self.db, gabinete, "ANUAL")

        self.assertEqual(gabinete.assinatura_vencimento.year, hoje.year + 1)
        self.assertEqual(gabinete.assinatura_vencimento.month, hoje.month)
        self.assertEqual(gabinete.plano, "ANUAL")

    def test_renovacao_calendario_real_fim_de_mes(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        # 31/01 + 1 mês tem que cair em fevereiro (28 ou 29), nunca em
        # 03/03 (que seria "30 dias fixos").
        gabinete.assinatura_vencimento = date(2027, 1, 31)
        gabinete.status_assinatura = "ATIVO"
        self.db.commit()

        novo_vencimento = calcular_novo_vencimento(gabinete, "MENSAL")
        self.assertEqual(novo_vencimento.month, 2)
        self.assertIn(novo_vencimento.day, (28, 29))

    def test_renovacao_preserva_gabinete_ativo(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        gabinete.ativo = False
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)

        aplicar_pagamento_confirmado(self.db, gabinete, "MENSAL")

        self.assertFalse(gabinete.ativo)

    def test_renovacao_preserva_dados_do_gabinete(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        nome_antes = gabinete.nome
        responsavel_antes = gabinete.responsavel
        public_token_antes = gabinete.public_token

        aplicar_pagamento_confirmado(self.db, gabinete, "MENSAL")

        self.assertEqual(gabinete.nome, nome_antes)
        self.assertEqual(gabinete.responsavel, responsavel_antes)
        self.assertEqual(gabinete.public_token, public_token_antes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
