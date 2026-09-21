"""Testes da Fase 1 — controle de validade/assinatura do Gabinete 360.

Cobre exatamente os cenários pedidos: trial válido, trial vencido,
assinatura ativa válida, assinatura vencida, SUPERADMIN, gabinete
ativo/inativo e usuário pertencente a outro gabinete — além da criação
de gabinete (trial de 7 dias) e da validação do ajuste manual pelo
SUPERADMIN.

Precisa de um PostgreSQL real (nunca SQLite como referência — ver
requisito 17 da Fase 1). Cria e remove seus próprios dados a cada
teste; nunca lê nem depende de dados pré-existentes no banco.

Uso:
    DATABASE_URL=postgresql://usuario:senha@localhost/sigab_teste \
    SECRET_KEY=qualquer-coisa-com-32-caracteres-ou-mais \
    AMBIENTE=local \
    python3 -m unittest tests.test_assinatura -v

(a suíte já assume que `alembic upgrade head` foi executado neste banco)
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.contexto import (  # noqa: E402
    GabineteNaoSelecionado,
    GabineteVencido,
    obter_contexto_atual,
)
from app.core.database import SessionLocal  # noqa: E402
from app.core.security import gerar_hash_senha  # noqa: E402
from app.core.tempo import hoje_operacional  # noqa: E402
from app.models.categoria import Categoria  # noqa: E402
from app.models.gabinete import Gabinete  # noqa: E402
from app.models.membro_gabinete import MembroGabinete  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.services.gabinete_service import GabineteService  # noqa: E402

DIAS_TRIAL_PADRAO = 7


class FakeRequest:
    """Substitui fastapi.Request nestes testes: obter_contexto_atual só
    lê/escreve request.session (aqui, um dict simples) e guarda o
    contexto resolvido em request.state — nunca usa mais nada do objeto
    real, então este substituto mínimo é suficiente e não depende de
    nenhum framework web para o teste rodar."""

    def __init__(self, gabinete_id=None):
        self.session = {}
        if gabinete_id is not None:
            self.session["gabinete_id"] = gabinete_id
        self.state = SimpleNamespace()


class BaseTesteAssinatura(unittest.TestCase):
    """Cria/limpa seus próprios dados — nunca reaproveita nem apaga nada
    que já existia no banco antes do teste rodar."""

    _contador = 0

    def setUp(self):
        self.db = SessionLocal()
        BaseTesteAssinatura._contador += 1
        self.sufixo = f"Fase1Teste{BaseTesteAssinatura._contador}"
        self._usuarios_ids: list[int] = []
        self._gabinetes_ids: list[int] = []

    def tearDown(self):
        # Ordem que respeita as FKs: categorias/membros antes de
        # usuarios/gabinetes.
        if self._gabinetes_ids:
            self.db.query(Categoria).filter(
                Categoria.gabinete_id.in_(self._gabinetes_ids)
            ).delete(synchronize_session=False)
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
        gabinete.assinatura_vencimento = date.today() + timedelta(days=dias_para_vencer)
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


class TesteCriacaoGabinete(BaseTesteAssinatura):
    def test_gabinete_novo_comeca_em_trial_com_7_dias(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        self.assertEqual(gabinete.status_assinatura, "TRIAL")
        self.assertIsNone(gabinete.plano)
        self.assertEqual(gabinete.assinatura_inicio, date.today())
        self.assertEqual(
            gabinete.assinatura_vencimento, date.today() + timedelta(days=DIAS_TRIAL_PADRAO)
        )
        self.assertFalse(gabinete.assinatura_vencida)


class TesteValidadeContexto(BaseTesteAssinatura):
    """Os 7 cenários pedidos no requisito 18."""

    def test_trial_valido_funciona_normalmente(self):
        gabinete, usuario = self._criar_gabinete_com_admin()
        request = FakeRequest(gabinete_id=gabinete.id)
        contexto = obter_contexto_atual(request, self.db, usuario)
        self.assertEqual(contexto.gabinete_id, gabinete.id)
        self.assertEqual(contexto.perfil, "ADMIN")

    def test_trial_vencido_bloqueia(self):
        gabinete, usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        request = FakeRequest(gabinete_id=gabinete.id)
        with self.assertRaises(GabineteVencido):
            obter_contexto_atual(request, self.db, usuario)

    def test_assinatura_ativa_valida_funciona_normalmente(self):
        gabinete, usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "ATIVO", dias_para_vencer=20, plano="MENSAL")
        request = FakeRequest(gabinete_id=gabinete.id)
        contexto = obter_contexto_atual(request, self.db, usuario)
        self.assertEqual(contexto.gabinete_id, gabinete.id)

    def test_assinatura_vencida_bloqueia(self):
        gabinete, usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "ATIVO", dias_para_vencer=-5, plano="ANUAL")
        request = FakeRequest(gabinete_id=gabinete.id)
        with self.assertRaises(GabineteVencido):
            obter_contexto_atual(request, self.db, usuario)

    def test_superadmin_nunca_e_bloqueado_por_validade(self):
        gabinete, _usuario_admin = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-30)
        superadmin = self._criar_superadmin()
        # Cenário defensivo: mesmo que um SUPERADMIN acabe com um vínculo
        # de MembroGabinete e gabinete_id na sessão (nunca acontece pelo
        # fluxo normal de login, ver app/modules/auth/controller.py), a
        # checagem de validade dentro de obter_contexto_atual precisa
        # ignorá-lo mesmo assim.
        membro = MembroGabinete(
            usuario_id=superadmin.id, gabinete_id=gabinete.id, perfil="ADMIN", ativo=True
        )
        self.db.add(membro)
        self.db.commit()
        request = FakeRequest(gabinete_id=gabinete.id)
        contexto = obter_contexto_atual(request, self.db, superadmin)
        self.assertEqual(contexto.gabinete_id, gabinete.id)

    def test_gabinete_inativo_bloqueia_mesmo_com_assinatura_valida(self):
        gabinete, usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "ATIVO", dias_para_vencer=20, plano="MENSAL")
        gabinete.ativo = False
        self.db.commit()
        request = FakeRequest(gabinete_id=gabinete.id)
        with self.assertRaises(GabineteNaoSelecionado):
            obter_contexto_atual(request, self.db, usuario)

    def test_gabinete_ativo_com_assinatura_valida_funciona(self):
        gabinete, usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "ATIVO", dias_para_vencer=20, plano="MENSAL")
        self.assertTrue(gabinete.ativo)
        request = FakeRequest(gabinete_id=gabinete.id)
        contexto = obter_contexto_atual(request, self.db, usuario)
        self.assertEqual(contexto.gabinete_id, gabinete.id)

    def test_usuario_de_outro_gabinete_e_bloqueado(self):
        gabinete_a, usuario_a = self._criar_gabinete_com_admin("A")
        gabinete_b, _usuario_b = self._criar_gabinete_com_admin("B")
        # usuario_a nunca teve MembroGabinete em gabinete_b — mas alguém
        # adulterou (ou uma sessão antiga guardou) gabinete_id=B.
        request = FakeRequest(gabinete_id=gabinete_b.id)
        with self.assertRaises(GabineteNaoSelecionado):
            obter_contexto_atual(request, self.db, usuario_a)
        # Confirma que gabinete_id foi removido da sessão (mesmo
        # comportamento de sempre, preservado).
        self.assertNotIn("gabinete_id", request.session)


class TesteAjusteManualSuperadmin(BaseTesteAssinatura):
    def test_atualizar_assinatura_superadmin_aplica_valores(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        inicio = date.today()
        vencimento = inicio + timedelta(days=365)
        GabineteService.atualizar_assinatura_superadmin(
            self.db, gabinete, "ATIVO", "ANUAL", inicio, vencimento
        )
        self.assertEqual(gabinete.status_assinatura, "ATIVO")
        self.assertEqual(gabinete.plano, "ANUAL")
        self.assertEqual(gabinete.assinatura_inicio, inicio)
        self.assertEqual(gabinete.assinatura_vencimento, vencimento)

    def test_atualizar_assinatura_rejeita_status_invalido(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        with self.assertRaises(ValueError):
            GabineteService.atualizar_assinatura_superadmin(
                self.db, gabinete, "CANCELADO", None, date.today(), date.today()
            )

    def test_atualizar_assinatura_rejeita_plano_invalido(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        with self.assertRaises(ValueError):
            GabineteService.atualizar_assinatura_superadmin(
                self.db, gabinete, "ATIVO", "TRIMESTRAL", date.today(), date.today() + timedelta(days=30)
            )

    def test_atualizar_assinatura_rejeita_vencimento_antes_do_inicio(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        inicio = date.today()
        with self.assertRaises(ValueError):
            GabineteService.atualizar_assinatura_superadmin(
                self.db, gabinete, "ATIVO", "MENSAL", inicio, inicio - timedelta(days=1)
            )


class TesteFusoOperacional(BaseTesteAssinatura):
    """Correção da auditoria (item 10.1): a validade precisa considerar o
    dia civil de America/Sao_Paulo, nunca o fuso do servidor. Os dois
    testes abaixo fixam o instante/"hoje" artificialmente — não dependem
    do relógio real da máquina que roda a suíte, então continuam válidos
    mesmo fora da janela de 3h em que UTC e Brasília diferem."""

    def test_hoje_operacional_usa_fuso_sao_paulo_nao_utc(self):
        # 2026-09-22 01:00 UTC == 2026-09-21 22:00 em America/Sao_Paulo.
        # Um servidor em UTC (o caso comum em Render/Neon) já considera
        # "hoje" == 22/09 nesse instante; o dia operacional real, em
        # Brasília, ainda é 21/09.
        instante_utc = datetime(2026, 9, 22, 1, 0, tzinfo=ZoneInfo("UTC"))

        class _DatetimeFixo(datetime):
            @classmethod
            def now(cls, tz=None):
                return instante_utc.astimezone(tz) if tz else instante_utc

        with patch("app.core.tempo.datetime", _DatetimeFixo):
            resultado = hoje_operacional()

        self.assertEqual(resultado, date(2026, 9, 21))
        self.assertNotEqual(resultado, instante_utc.date())  # UTC diria 22/09

    def test_assinatura_vencida_respeita_dia_civil_completo(self):
        gabinete, _usuario = self._criar_gabinete_com_admin()
        gabinete.assinatura_vencimento = date(2026, 9, 21)
        self.db.commit()

        with patch("app.models.gabinete.hoje_operacional", return_value=date(2026, 9, 21)):
            self.assertFalse(
                gabinete.assinatura_vencida,
                "no proprio dia do vencimento (fuso operacional) ainda deve funcionar",
            )

        with patch("app.models.gabinete.hoje_operacional", return_value=date(2026, 9, 22)):
            self.assertTrue(
                gabinete.assinatura_vencida,
                "no dia seguinte (fuso operacional) já deve estar vencido",
            )


class TesteIsolamentoPaginaAssinatura(BaseTesteAssinatura):
    """Correção da auditoria (item 10.2): /assinatura não pode mais
    revelar nome/vencimento de um gabinete ao qual o usuário não tem mais
    vínculo ativo, mesmo com uma sessão antiga que ainda carregue aquele
    gabinete_id."""

    def test_sessao_antiga_apos_remocao_do_vinculo_nao_revela_gabinete(self):
        from app.modules.assinatura.controller import vencido as pagina_assinatura

        gabinete, usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)

        request = FakeRequest(gabinete_id=gabinete.id)

        # Com o vínculo intacto, a página mostra o gabinete normalmente.
        resposta = pagina_assinatura(request, self.db, usuario)
        corpo = resposta.body.decode("utf-8")
        self.assertIn(gabinete.nome, corpo)

        # Remove o vínculo (ex.: SUPERADMIN retirou o acesso) sem
        # invalidar a sessão antiga — o cookie assinado do usuário ainda
        # carrega o mesmo gabinete_id de antes.
        membro = self.db.scalar(
            select(MembroGabinete).where(
                MembroGabinete.usuario_id == usuario.id,
                MembroGabinete.gabinete_id == gabinete.id,
            )
        )
        self.db.delete(membro)
        self.db.commit()

        resposta2 = pagina_assinatura(request, self.db, usuario)
        corpo2 = resposta2.body.decode("utf-8")
        self.assertNotIn(gabinete.nome, corpo2)
        self.assertNotIn(str(gabinete.assinatura_vencimento.year), corpo2)
        # gabinete_id obsoleto precisa ser removido da sessão — a próxima
        # navegação (recarregar "/", "Sair") segue o fluxo normal de
        # contexto inválido já existente.
        self.assertNotIn("gabinete_id", request.session)

    def test_sem_loop_entre_assinatura_login_selecionar_gabinete(self):
        """Depois da correção, chamar a página de novo com a sessão já
        sem gabinete_id não deve levantar NaoAutenticado/GabineteVencido/
        GabineteNaoSelecionado — /assinatura nunca depende de
        obter_contexto_atual, então nunca entra nesse ciclo."""
        from app.modules.assinatura.controller import vencido as pagina_assinatura

        gabinete, usuario = self._criar_gabinete_com_admin()
        self._forcar_assinatura(gabinete, "TRIAL", dias_para_vencer=-1)
        request = FakeRequest(gabinete_id=gabinete.id)

        membro = self.db.scalar(
            select(MembroGabinete).where(
                MembroGabinete.usuario_id == usuario.id,
                MembroGabinete.gabinete_id == gabinete.id,
            )
        )
        self.db.delete(membro)
        self.db.commit()

        # Primeira chamada: detecta o vínculo ausente, remove gabinete_id.
        pagina_assinatura(request, self.db, usuario)
        self.assertNotIn("gabinete_id", request.session)

        # Segunda chamada, sessão já sem gabinete_id: continua respondendo
        # normalmente (200, contexto genérico), sem lançar nada.
        resposta = pagina_assinatura(request, self.db, usuario)
        self.assertIsNotNone(resposta.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
