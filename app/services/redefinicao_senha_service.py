import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.security import gerar_hash_senha
from app.models.redefinicao_senha import RedefinicaoSenha
from app.models.usuario import Usuario
from app.services.email_sender_service import EmailNaoConfiguradoError, EmailSenderService

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 30 minutos — curto de propósito (é um link de posse de e-mail, não uma
# sessão de trabalho) e consistente com o padrão já usado pelo módulo de
# atendimento público para expiração de link, adaptado aqui em minutos.
VALIDADE_MINUTOS = 30

SENHA_MINIMO_CARACTERES = 8


def _hash_token(token: str) -> str:
    # sha256 (não Argon2) de propósito: o token em si já é
    # criptograficamente aleatório e de alta entropia (secrets.token_urlsafe,
    # 32 bytes) — o hash aqui existe só para não guardar o valor em texto
    # puro no banco, não para resistir a um chute de senha humana fraca
    # (que é o problema que Argon2/security.py resolve para senhas reais).
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RedefinicaoSenhaService:
    """Fluxo "esqueci minha senha" — ver app/modules/perfil/controller.py.
    Toda operação aqui é deliberadamente genérica sobre "o e-mail existe
    ou não" (mesma lógica anti-enumeração de AuthService.autenticar): o
    controller nunca deve revelar, pela resposta, se um e-mail está ou não
    cadastrado."""

    @staticmethod
    def solicitar(db: Session, email: str, url_base: str) -> None:
        """Gera um token novo e tenta enviar por e-mail SE o endereço
        corresponder a um usuário ativo — silenciosamente não faz nada
        (nem cria token) caso contrário. Nunca levanta por "e-mail não
        encontrado"; falha de SMTP é só registrada em log, porque revelar
        isso ao usuário também differenciaria a resposta."""
        email_normalizado = (email or "").strip().lower()
        if not email_normalizado:
            return

        usuario = db.scalar(select(Usuario).where(Usuario.email == email_normalizado))
        if usuario is None or not usuario.ativo:
            return

        token = secrets.token_urlsafe(32)
        agora = datetime.utcnow()
        redefinicao = RedefinicaoSenha(
            usuario_id=usuario.id,
            token_hash=_hash_token(token),
            criado_em=agora,
            expira_em=agora + timedelta(minutes=VALIDADE_MINUTOS),
        )
        db.add(redefinicao)
        db.commit()

        link = f"{url_base.rstrip('/')}/redefinir-senha/{token}"
        assunto = "Gabinete 360 — Redefinição de senha"
        texto = (
            f"Olá, {usuario.nome}.\n\n"
            "Recebemos uma solicitação para redefinir a senha da sua conta no Gabinete 360.\n\n"
            f"Para continuar, acesse o link abaixo (válido por {VALIDADE_MINUTOS} minutos, uso único):\n"
            f"{link}\n\n"
            "Se você não solicitou isso, apenas ignore este e-mail — sua senha atual continua válida."
        )
        html = templates.get_template("email/redefinir_senha.html").render(
            {"nome": usuario.nome, "link": link, "validade_minutos": VALIDADE_MINUTOS}
        )
        try:
            EmailSenderService.enviar(usuario.email, assunto, texto, html)
        except EmailNaoConfiguradoError:
            logger.warning(
                "Token de redefinição de senha gerado para usuario_id=%s, mas SMTP não está "
                "configurado neste ambiente — nenhum e-mail foi enviado.",
                usuario.id,
            )
        except Exception:
            logger.exception(
                "Falha ao enviar e-mail de redefinição de senha (usuario_id=%s).", usuario.id
            )

    @staticmethod
    def obter_valida(db: Session, token: str) -> RedefinicaoSenha | None:
        """Só devolve a redefinição se o token existir, ainda não tiver
        sido usado e ainda não tiver expirado — qualquer outro caso é
        tratado como "link inválido", sem diferenciar qual desses três
        motivos é (o controller mostra sempre a mesma mensagem genérica)."""
        if not token:
            return None
        redefinicao = db.scalar(
            select(RedefinicaoSenha).where(RedefinicaoSenha.token_hash == _hash_token(token))
        )
        if (
            redefinicao is None
            or redefinicao.usado_em is not None
            or redefinicao.expira_em < datetime.utcnow()
        ):
            return None
        return redefinicao

    @staticmethod
    def redefinir(db: Session, token: str, nova_senha: str) -> bool:
        """Confirma o token (uso único — obter_valida já garante que ainda
        não foi usado nem expirou) e troca a senha. Invalida também
        qualquer outro token de redefinição ainda pendente do mesmo
        usuário — depois de uma redefinição bem-sucedida, um link antigo
        (ex.: de um e-mail anterior, esquecido numa caixa de entrada) não
        deve continuar valendo. Retorna False sem alterar nada se o token
        não for (mais) válido."""
        redefinicao = RedefinicaoSenhaService.obter_valida(db, token)
        if redefinicao is None:
            return False
        if len(nova_senha or "") < SENHA_MINIMO_CARACTERES:
            raise ValueError(f"Senha muito curta — mínimo {SENHA_MINIMO_CARACTERES} caracteres.")

        agora = datetime.utcnow()
        usuario = db.get(Usuario, redefinicao.usuario_id)
        usuario.senha_hash = gerar_hash_senha(nova_senha)
        redefinicao.usado_em = agora

        outros_pendentes = db.scalars(
            select(RedefinicaoSenha).where(
                RedefinicaoSenha.usuario_id == redefinicao.usuario_id,
                RedefinicaoSenha.id != redefinicao.id,
                RedefinicaoSenha.usado_em.is_(None),
            )
        ).all()
        for pendente in outros_pendentes:
            pendente.usado_em = agora

        db.commit()
        return True
