import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.services.daily_email_service import DailyEmailService

# Rota chamada por um agendador EXTERNO (cron externo, GitHub Actions
# scheduled workflow etc. — a definir), nunca por um usuário logado no
# navegador. Por isso a autorização aqui não usa sessão/cookie nem
# exigir_superadmin/exigir_perfil (não existe usuário autenticado nessa
# chamada) — usa um token secreto de variável de ambiente, comparado com
# secrets.compare_digest para não vazar o valor por timing.
router = APIRouter(prefix="/jobs", tags=["Jobs"])


def _exigir_token_valido(authorization: str | None = Header(default=None)) -> None:
    if not settings.jobs_token:
        # Sem JOBS_TOKEN configurado, a rota fica sempre fechada — nunca
        # existe um "token padrão" esquecido em produção.
        raise HTTPException(status_code=503, detail="Job não configurado.")

    esperado = f"Bearer {settings.jobs_token}"
    if not authorization or not secrets.compare_digest(authorization, esperado):
        raise HTTPException(status_code=401, detail="Token inválido.")


@router.post("/enviar-diario")
def enviar_diario(
    db: Session = Depends(get_db),
    _: None = Depends(_exigir_token_valido),
) -> dict:
    """Envia o e-mail diário de TODOS os gabinetes ativos para o dia atual
    (America/Sao_Paulo). Idempotente por gabinete — ver
    DailyEmailService.enviar_diario/GabineteService.ja_enviou_diario_hoje.
    Não retorna nenhum dado de gabinete além de contagem/status — não é uma
    rota de leitura de dado de tenant. Resposta deliberadamente enxuta (sem
    o detalhe por gabinete): agendadores externos como cron-job.org têm um
    limite de tamanho de resposta, e o detalhe completo não é necessário
    para confirmar que o job rodou — só a contagem agregada."""
    resultados = DailyEmailService.enviar_diario_todos_os_gabinetes(db)
    return {
        "status": "ok",
        "data": DailyEmailService.hoje_operacional().isoformat(),
        "total_gabinetes": len(resultados),
        "enviados": sum(1 for r in resultados if r["status"] == "enviado"),
    }
