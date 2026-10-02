"""Testes da Fase 3 — autocadastro público (/cadastro) do Gabinete 360.

Não testa fastapi.testclient.TestClient de propósito: este projeto nunca
usou TestClient em nenhum teste (confirmado antes de escrever este
arquivo) e a versão de Starlette instalada aqui exige um pacote adicional
("httpx2") só para isso — não vale adicionar uma dependência nova só para
testes quando o padrão já estabelecido (chamar os handlers diretamente,
com um FakeRequest mínimo, igual a test_assinatura.py/test_asaas.py) cobre
exatamente os mesmos cenários sem precisar subir um servidor ASGI de
verdade.

Prioriza cobertura dos riscos/invariantes da Fase 3 (CSRF, isolamento
multi-tenant, não-enumeração de e-mail, rollback, tamanho de campos,
trial/timezone) — não uma quantidade arbitrária de testes.

Precisa de um PostgreSQL real (nunca SQLite como referência de produção —
mesmo requisito das suítes de Fase 1/Fase 2).

Uso:
    DATABASE_URL=postgresql://usuario:senha@localhost/sigab_teste \
    SECRET_KEY=qualquer-coisa-com-32-caracteres-ou-mais \
    AMBIENTE=local \
    python3 -m unittest tests.test_cadastro -v

(a suíte já assume que `alembic upgrade head` foi executado neste banco)
"""

import os
import sys
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402

from app.core.contexto import (  # noqa: E402
    GabineteNaoSelecionado,
    GabineteVencido,
    obter_contexto_atual,
)
from app.core.database import SessionLocal  # noqa: E402
from app.core.tempo import hoje_operacional  # noqa: E402
from app.models.categoria import Categoria  # noqa: E402
from app.models.gabinete import Gabinete  # noqa: E402
from app.models.membro_gabinete import MembroGabinete  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.modules.cadastro.controller import (  # noqa: E402
    CHAVE_SESSAO_CSRF,
    MENSAGEM_ERRO_GENERICA,
    criar_cadastro,
    formulario_cadastro,
)

SENHA_PADRAO = "senha12345"


class FakeRequest:
    """Mesmo substituto mínimo de fastapi.Request usado em
    test_assinatura.py/test_asaas.py — os handlers de /cadastro só leem e
    escrevem request.session (aqui, um dict simples) e, desde a Fase 4,
    request.query_params.get("plano") — nunca mais nada do objeto real."""

    def __init__(self, query_params: dict | None = None):
        self.session: dict = {}
        self.state = SimpleNamespace()
        self.query_params = query_params or {}


class BaseTesteCadastro(unittest.TestCase):
    """Cria/limpa seus próprios dados — nunca reaproveita nem apaga nada
    que já existia no banco antes do teste rodar."""

    _contador = 0

    def setUp(self):
        self.db = SessionLocal()
        BaseTesteCadastro._contador += 1
        self.sufixo = f"Cad{BaseTesteCadastro._contador}"
        self._usuarios_ids: list[int] = []
        self._gabinetes_ids: list[int] = []

    def tearDown(self):
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

    def _email(self, extra: str = "") -> str:
        return f"admin.{self.sufixo}{extra}@teste.local".lower()

    def _obter_csrf(self, request: FakeRequest) -> str:
        formulario_cadastro(request)
        return request.session[CHAVE_SESSAO_CSRF]

    def _submeter(self, request: FakeRequest, *, csrf: str | None = None, **campos):
        dados = {
            "nome_gabinete": f"Gabinete {self.sufixo}",
            "nome_admin": "Admin Teste",
            "email_admin": self._email(),
            "senha_admin": SENHA_PADRAO,
            "confirmar_senha": SENHA_PADRAO,
        }
        dados.update(campos)
        token = self._obter_csrf(request) if csrf is None else csrf
        return criar_cadastro(
            request,
            nome_gabinete=dados["nome_gabinete"],
            nome_admin=dados["nome_admin"],
            email_admin=dados["email_admin"],
            senha_admin=dados["senha_admin"],
            confirmar_senha=dados["confirmar_senha"],
            csrf_token=token,
            db=self.db,
        )

    def _criar_via_cadastro_publico(self, extra: str = "") -> tuple[Gabinete, Usuario]:
        request = FakeRequest()
        nome_gabinete = f"Gabinete {self.sufixo}{extra}"
        email = self._email(extra)
        self._submeter(request, nome_gabinete=nome_gabinete, email_admin=email)
        gabinete = self.db.scalar(select(Gabinete).where(Gabinete.nome == nome_gabinete))
        usuario = self.db.scalar(select(Usuario).where(Usuario.email == email))
        self.assertIsNotNone(gabinete)
        self.assertIsNotNone(usuario)
        self._gabinetes_ids.append(gabinete.id)
        self._usuarios_ids.append(usuario.id)
        return gabinete, usuario

    def _contar_gabinetes(self) -> int:
        return self.db.scalar(select(func.count()).select_from(Gabinete)) or 0


class TesteCadastroValido(BaseTesteCadastro):
    def test_cadastro_valido_cria_gabinete_admin_membro_e_trial(self):
        total_antes = self._contar_gabinetes()
        gabinete, usuario = self._criar_via_cadastro_publico()

        # Exatamente um novo Gabinete — nunca um órfão nem mais de um.
        self.assertEqual(self._contar_gabinetes(), total_antes + 1)
        self.assertEqual(
            self.db.scalar(
                select(func.count()).select_from(Gabinete).where(Gabinete.id == gabinete.id)
            ),
            1,
        )

        membro = self.db.scalar(
            select(MembroGabinete).where(
                MembroGabinete.usuario_id == usuario.id, MembroGabinete.gabinete_id == gabinete.id
            )
        )
        self.assertIsNotNone(membro)
        self.assertEqual(membro.perfil, "ADMIN")
        self.assertTrue(membro.ativo)

        # Requisito explícito: autocadastro público nunca cria Superadmin.
        self.assertFalse(usuario.super_admin)
        self.assertTrue(usuario.ativo)

        # Trial de 7 dias, reaproveitando hoje_operacional() como oráculo —
        # nunca uma segunda conta de dias aqui.
        self.assertEqual(gabinete.status_assinatura, "TRIAL")
        self.assertEqual(gabinete.assinatura_inicio, hoje_operacional())
        self.assertEqual(gabinete.assinatura_vencimento, hoje_operacional() + timedelta(days=7))

    def test_login_automatico_apos_cadastro(self):
        request = FakeRequest()
        nome_gabinete = f"Gabinete {self.sufixo}"
        email = self._email()
        self._submeter(request, nome_gabinete=nome_gabinete, email_admin=email)

        gabinete = self.db.scalar(select(Gabinete).where(Gabinete.nome == nome_gabinete))
        usuario = self.db.scalar(select(Usuario).where(Usuario.email == email))
        self._gabinetes_ids.append(gabinete.id)
        self._usuarios_ids.append(usuario.id)

        # Mesmo mecanismo de sessão do POST /login — só usuario_id/gabinete_id.
        self.assertEqual(request.session["usuario_id"], usuario.id)
        self.assertEqual(request.session["gabinete_id"], gabinete.id)

        # E essa sessão já passa pela checagem real de contexto, como
        # qualquer sessão de login normal.
        contexto = obter_contexto_atual(request, self.db, usuario)
        self.assertEqual(contexto.gabinete_id, gabinete.id)
        self.assertEqual(contexto.perfil, "ADMIN")


class TesteCsrf(BaseTesteCadastro):
    def test_csrf_ausente_bloqueia_cadastro(self):
        request = FakeRequest()
        formulario_cadastro(request)  # gera o token na sessão, mas não o usamos
        resposta = criar_cadastro(
            request,
            nome_gabinete=f"Gabinete {self.sufixo}",
            nome_admin="Admin Teste",
            email_admin=self._email(),
            senha_admin=SENHA_PADRAO,
            confirmar_senha=SENHA_PADRAO,
            csrf_token="",
            db=self.db,
        )
        self.assertEqual(resposta.context["erro"], MENSAGEM_ERRO_GENERICA)
        self.assertIsNone(self.db.scalar(select(Usuario).where(Usuario.email == self._email())))

    def test_csrf_invalido_bloqueia_cadastro(self):
        request = FakeRequest()
        formulario_cadastro(request)
        resposta = criar_cadastro(
            request,
            nome_gabinete=f"Gabinete {self.sufixo}",
            nome_admin="Admin Teste",
            email_admin=self._email(),
            senha_admin=SENHA_PADRAO,
            confirmar_senha=SENHA_PADRAO,
            csrf_token="token-forjado-pelo-atacante",
            db=self.db,
        )
        self.assertEqual(resposta.context["erro"], MENSAGEM_ERRO_GENERICA)
        self.assertIsNone(self.db.scalar(select(Usuario).where(Usuario.email == self._email())))


class TesteJaAutenticado(BaseTesteCadastro):
    def test_get_cadastro_ja_autenticado_redireciona(self):
        _gabinete, usuario = self._criar_via_cadastro_publico()
        request = FakeRequest()
        request.session["usuario_id"] = usuario.id
        resposta = formulario_cadastro(request)
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "/")

    def test_post_cadastro_ja_autenticado_nao_cria_outro_gabinete(self):
        _gabinete, usuario = self._criar_via_cadastro_publico()
        total_antes = self._contar_gabinetes()

        request = FakeRequest()
        request.session["usuario_id"] = usuario.id
        outro_nome = f"Gabinete {self.sufixo}-outro"
        resposta = criar_cadastro(
            request,
            nome_gabinete=outro_nome,
            nome_admin="Outro Admin",
            email_admin=self._email("outro"),
            senha_admin=SENHA_PADRAO,
            confirmar_senha=SENHA_PADRAO,
            csrf_token="",  # nem chega a ser checado — curto-circuita antes
            db=self.db,
        )
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "/")
        self.assertEqual(self._contar_gabinetes(), total_antes)
        self.assertIsNone(self.db.scalar(select(Gabinete).where(Gabinete.nome == outro_nome)))


class TesteEnumeracaoDeEmail(BaseTesteCadastro):
    def test_email_duplicado_usa_mensagem_generica_e_nao_cria_segundo_gabinete(self):
        _gabinete_a, usuario_a = self._criar_via_cadastro_publico()
        total_antes = self._contar_gabinetes()

        request_b = FakeRequest()
        nome_gabinete_b = f"Gabinete {self.sufixo}-B"
        resposta = self._submeter(
            request_b, nome_gabinete=nome_gabinete_b, email_admin=usuario_a.email
        )

        # Mensagem idêntica à de qualquer outra falha de validação — nunca
        # "já existe um usuário com este e-mail" (a mensagem original do
        # service), que confirmaria a existência da conta a quem está
        # tentando enumerar e-mails.
        self.assertEqual(resposta.context["erro"], MENSAGEM_ERRO_GENERICA)
        self.assertNotIn("usuário", resposta.context["erro"].lower())
        self.assertEqual(self._contar_gabinetes(), total_antes)
        self.assertIsNone(self.db.scalar(select(Gabinete).where(Gabinete.nome == nome_gabinete_b)))


class TesteValidacaoDeCampos(BaseTesteCadastro):
    def test_campos_invalidos_sao_rejeitados_sem_criar_nada(self):
        casos = {
            "nome_gabinete_vazio": {"nome_gabinete": " "},
            "nome_admin_vazio": {"nome_admin": ""},
            "email_sem_arroba": {"email_admin": "nao-e-email"},
            "email_maior_que_150_chars": {"email_admin": ("a" * 150) + "@teste.local"},
            "nome_gabinete_maior_que_150_chars": {"nome_gabinete": "G" * 151},
            "senha_curta": {"senha_admin": "curta12", "confirmar_senha": "curta12"},
            "senha_maior_que_128_chars": {
                "senha_admin": "s" * 129,
                "confirmar_senha": "s" * 129,
            },
            "confirmacao_diferente": {"senha_admin": SENHA_PADRAO, "confirmar_senha": "outrasenha123"},
        }
        total_antes = self._contar_gabinetes()
        for descricao, campos in casos.items():
            with self.subTest(descricao):
                request = FakeRequest()
                email = self._email(descricao.replace("_", ""))
                dados = {"email_admin": email}
                dados.update(campos)
                resposta = self._submeter(request, **dados)
                self.assertIsNotNone(resposta.context["erro"])
                self.assertIsNone(self.db.scalar(select(Usuario).where(Usuario.email == email)))
        self.assertEqual(self._contar_gabinetes(), total_antes)


class TesteRollback(BaseTesteCadastro):
    def test_falha_durante_criacao_nao_deixa_registro_orfao(self):
        nome_gabinete = f"Gabinete {self.sufixo}"
        email = self._email()
        request = FakeRequest()

        # Força uma falha DEPOIS que Gabinete/Usuario/MembroGabinete já
        # foram adicionados à transação (ver GabineteService.
        # criar_gabinete_com_admin) mas ANTES do commit — exercita a mesma
        # garantia de tudo-ou-nada já existente no service, agora pelo
        # caminho público.
        with patch(
            "app.services.gabinete_service.Categoria", side_effect=RuntimeError("falha simulada")
        ):
            with self.assertRaises(RuntimeError):
                self._submeter(request, nome_gabinete=nome_gabinete, email_admin=email)

        self.assertIsNone(self.db.scalar(select(Gabinete).where(Gabinete.nome == nome_gabinete)))
        self.assertIsNone(self.db.scalar(select(Usuario).where(Usuario.email == email)))


class TesteMultiTenant(BaseTesteCadastro):
    def test_isolamento_entre_dois_cadastros_publicos(self):
        gabinete_a, usuario_a = self._criar_via_cadastro_publico("A")
        gabinete_b, _usuario_b = self._criar_via_cadastro_publico("B")
        self.assertNotEqual(gabinete_a.id, gabinete_b.id)

        # usuario_a nunca teve MembroGabinete em gabinete_b — mesma checagem
        # (obter_contexto_atual) usada por toda rota autenticada do sistema.
        request = FakeRequest()
        request.session["gabinete_id"] = gabinete_b.id
        with self.assertRaises(GabineteNaoSelecionado):
            obter_contexto_atual(request, self.db, usuario_a)
        self.assertNotIn("gabinete_id", request.session)

    def test_trial_expirado_segue_gabinetevencido_sem_excecao_especial(self):
        gabinete, usuario = self._criar_via_cadastro_publico()
        gabinete.assinatura_vencimento = hoje_operacional() - timedelta(days=1)
        self.db.commit()
        self.db.refresh(gabinete)

        request = FakeRequest()
        request.session["gabinete_id"] = gabinete.id
        with self.assertRaises(GabineteVencido):
            obter_contexto_atual(request, self.db, usuario)

        # Dados preservados — nada é apagado quando o trial vence.
        self.assertIsNotNone(self.db.scalar(select(Gabinete).where(Gabinete.id == gabinete.id)))


class TestePlanoFase4(BaseTesteCadastro):
    """Fase 4 — "plano" na querystring só decide PARA ONDE redirecionar
    depois do cadastro; nunca cria Checkout, nunca ativa/renova nada
    (isso continua exclusivo de /assinatura/checkout + webhook,
    nenhum dos dois tocado nesta fase)."""

    def test_sem_plano_comportamento_identico_ao_atual(self):
        request = FakeRequest()
        resposta = self._submeter(request)
        self.assertEqual(resposta.template.name, "cadastro/sucesso.html")
        gabinete = self.db.scalar(
            select(Gabinete).where(Gabinete.nome == f"Gabinete {self.sufixo}")
        )
        usuario = self.db.scalar(select(Usuario).where(Usuario.email == self._email()))
        self._gabinetes_ids.append(gabinete.id)
        self._usuarios_ids.append(usuario.id)

    def test_plano_mensal_redireciona_para_assinatura(self):
        request = FakeRequest(query_params={"plano": "mensal"})
        resposta = self._submeter(request)
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "/assinatura?plano=mensal")

        gabinete = self.db.scalar(
            select(Gabinete).where(Gabinete.nome == f"Gabinete {self.sufixo}")
        )
        usuario = self.db.scalar(select(Usuario).where(Usuario.email == self._email()))
        self._gabinetes_ids.append(gabinete.id)
        self._usuarios_ids.append(usuario.id)

        # Gabinete nasceu em TRIAL normalmente — "plano" na querystring
        # nunca ativa nem renova nada por si só.
        self.assertEqual(gabinete.status_assinatura, "TRIAL")
        # Login automático preservado (mesma garantia da Fase 3).
        self.assertEqual(request.session["usuario_id"], usuario.id)
        self.assertEqual(request.session["gabinete_id"], gabinete.id)

    def test_plano_anual_redireciona_para_assinatura(self):
        request = FakeRequest(query_params={"plano": "anual"})
        resposta = self._submeter(request)
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], "/assinatura?plano=anual")

        gabinete = self.db.scalar(
            select(Gabinete).where(Gabinete.nome == f"Gabinete {self.sufixo}")
        )
        self._gabinetes_ids.append(gabinete.id)
        self._usuarios_ids.append(
            self.db.scalar(select(Usuario).where(Usuario.email == self._email())).id
        )
        self.assertEqual(gabinete.status_assinatura, "TRIAL")

    def test_plano_invalido_tratado_como_ausente(self):
        for indice, valor in enumerate(
            ["trimestral", "", "MENSAL;DROP TABLE gabinetes", "<script>", "mensalx"]
        ):
            with self.subTest(valor=valor):
                request = FakeRequest(query_params={"plano": valor})
                email = self._email(f"inv{indice}")
                nome_gabinete = f"Gabinete {self.sufixo}-inv{indice}"
                resposta = self._submeter(
                    request, nome_gabinete=nome_gabinete, email_admin=email
                )
                # Mesmo comportamento de "sem plano" — nunca um erro, nunca
                # um redirect para /assinatura com um valor não permitido.
                self.assertEqual(resposta.template.name, "cadastro/sucesso.html")
                gabinete = self.db.scalar(select(Gabinete).where(Gabinete.nome == nome_gabinete))
                usuario = self.db.scalar(select(Usuario).where(Usuario.email == email))
                self._gabinetes_ids.append(gabinete.id)
                self._usuarios_ids.append(usuario.id)

    def test_plano_manipulado_nunca_afeta_tenant_criado(self):
        """Mesmo com "plano" adulterado, o Checkout subsequente (fora
        desta função — ver test_asaas.py) só poderia pertencer ao
        gabinete que a sessão aponta, que é sempre o recém-criado — este
        teste confirma que o valor de "plano" não influencia em nada além
        do redirect: nenhum segundo gabinete, nenhuma mudança de tenant."""
        total_antes = self._contar_gabinetes()
        request = FakeRequest(query_params={"plano": "ANUAL"})
        resposta = self._submeter(request)
        self.assertEqual(self._contar_gabinetes(), total_antes + 1)

        gabinete = self.db.scalar(
            select(Gabinete).where(Gabinete.nome == f"Gabinete {self.sufixo}")
        )
        self._gabinetes_ids.append(gabinete.id)
        self._usuarios_ids.append(
            self.db.scalar(select(Usuario).where(Usuario.email == self._email())).id
        )
        self.assertEqual(resposta.headers["location"], "/assinatura?plano=anual")
        self.assertEqual(request.session["gabinete_id"], gabinete.id)

    def test_formulario_get_preserva_plano_para_o_template(self):
        request = FakeRequest(query_params={"plano": "mensal"})
        resposta = formulario_cadastro(request)
        self.assertEqual(resposta.context["plano"], "MENSAL")

        request_invalido = FakeRequest(query_params={"plano": "vitalicio"})
        resposta_invalida = formulario_cadastro(request_invalido)
        self.assertIsNone(resposta_invalida.context["plano"])


class TesteFormularioContextualAoPlano(BaseTesteCadastro):
    """Ajuste de UX (pós-Fase 4): o texto de /cadastro reflete o plano da
    querystring — puramente apresentação, reaproveitando o "plano" que o
    controller já disponibilizava no contexto desde a Fase 4. Nenhum
    destes testes toca o banco (GET /cadastro não cria nada)."""

    def test_sem_plano_mostra_texto_de_teste_gratis(self):
        html = formulario_cadastro(FakeRequest()).body.decode("utf-8")
        self.assertIn("Criar conta gratuita", html)
        self.assertIn("CRIAR MINHA CONTA GRATUITA", html)
        self.assertNotIn("Assine o Gabinete 360", html)

    def test_plano_mensal_mostra_texto_de_assinatura_mensal(self):
        request = FakeRequest(query_params={"plano": "mensal"})
        html = formulario_cadastro(request).body.decode("utf-8")
        self.assertIn("Assine o Gabinete 360", html)
        self.assertIn("Plano Mensal", html)
        self.assertIn("R$ 99,90/mês", html)
        self.assertIn("CONTINUAR PARA PAGAMENTO", html)
        self.assertNotIn("CRIAR MINHA CONTA GRATUITA", html)

    def test_plano_anual_mostra_texto_de_assinatura_anual(self):
        request = FakeRequest(query_params={"plano": "anual"})
        html = formulario_cadastro(request).body.decode("utf-8")
        self.assertIn("Assine o Gabinete 360", html)
        self.assertIn("Plano Anual", html)
        self.assertIn("Total de R$ 799,00/ano", html)
        self.assertIn("CONTINUAR PARA PAGAMENTO", html)
        self.assertNotIn("CRIAR MINHA CONTA GRATUITA", html)

    def test_plano_invalido_mostra_texto_de_teste_gratis(self):
        request = FakeRequest(query_params={"plano": "vitalicio"})
        html = formulario_cadastro(request).body.decode("utf-8")
        self.assertIn("Criar conta gratuita", html)
        self.assertIn("CRIAR MINHA CONTA GRATUITA", html)
        self.assertNotIn("Assine o Gabinete 360", html)


if __name__ == "__main__":
    unittest.main()
