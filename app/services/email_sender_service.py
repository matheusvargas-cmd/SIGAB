import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailNaoConfiguradoError(Exception):
    """SMTP_HOST/SMTP_FROM ausentes — nenhuma tentativa de envio é feita."""


class EmailSenderService:
    """Só sabe falar SMTP — não conhece Gabinete, Agenda, Eleitor nem
    Demanda. Qualquer provedor SMTP compatível funciona só configurando as
    variáveis de ambiente (SMTP_HOST/PORT/USER/PASSWORD/FROM/USE_TLS);
    nenhum provedor é assumido no código."""

    @staticmethod
    def enviar(destinatario: str, assunto: str, corpo_texto: str, corpo_html: str) -> None:
        if not settings.smtp_configurado:
            raise EmailNaoConfiguradoError(
                "SMTP não configurado (defina SMTP_HOST e SMTP_FROM) — nenhum e-mail foi enviado."
            )

        mensagem = EmailMessage()
        mensagem["Subject"] = assunto
        mensagem["From"] = settings.smtp_from
        mensagem["To"] = destinatario
        mensagem.set_content(corpo_texto)
        mensagem.add_alternative(corpo_html, subtype="html")

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as servidor:
            if settings.smtp_use_tls:
                servidor.starttls()
            if settings.smtp_user:
                servidor.login(settings.smtp_user, settings.smtp_password)
            servidor.send_message(mensagem)

        logger.info("E-mail enviado para %s (assunto: %s).", destinatario, assunto)
