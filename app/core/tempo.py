"""Data operacional do sistema — sempre America/Sao_Paulo, nunca o fuso
do servidor. Render/Neon normalmente rodam em UTC; `date.today()` ali
pode já estar num dia diferente do horário real de Brasília, sobretudo à
noite (a partir de 21h em Brasília já é o dia seguinte em UTC).

Único lugar que deveria conhecer esse fuso — qualquer regra de negócio
que precise de "hoje" (validade de assinatura, e-mail diário, etc.) usa
hoje_operacional() daqui, nunca date.today() direto nem uma segunda
ZoneInfo("America/Sao_Paulo") redeclarada em outro módulo.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO_OPERACIONAL = ZoneInfo("America/Sao_Paulo")


def hoje_operacional() -> date:
    return datetime.now(FUSO_OPERACIONAL).date()
