"""controle_validade_assinatura_gabinete

Fase 1 — Controle de validade/assinatura do Gabinete 360.

Adiciona a Gabinete: status_assinatura (TRIAL/ATIVO), plano (MENSAL/ANUAL,
nulo enquanto em TRIAL), assinatura_inicio e assinatura_vencimento.

Backfill de gabinetes já existentes: status_assinatura='ATIVO' e
assinatura_vencimento bem no futuro (10 anos a partir de assinatura_inicio)
— nunca 'TRIAL' com vencimento em 7 dias, o que bloquearia gabinetes já em
produção logo depois do deploy desta migration. Isso não altera nenhum
dado de negócio existente (Eleitor, Demanda, Agenda, etc.) e não depende
de nenhuma coluna nova ser preenchida manualmente depois — o SUPERADMIN
pode ajustar status/plano/vencimento reais de cada gabinete quando
quiser, pela tela /superadmin/gabinetes.

Revision ID: 082b4c3629e0
Revises: bc9c961bdf45
Create Date: 2026-09-21 12:37:35.278698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '082b4c3629e0'
down_revision: Union[str, Sequence[str], None] = 'bc9c961bdf45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('gabinetes', sa.Column('status_assinatura', sa.String(length=20), nullable=True))
    op.add_column('gabinetes', sa.Column('plano', sa.String(length=20), nullable=True))
    op.add_column('gabinetes', sa.Column('assinatura_inicio', sa.Date(), nullable=True))
    op.add_column('gabinetes', sa.Column('assinatura_vencimento', sa.Date(), nullable=True))

    dialeto = op.get_bind().dialect.name
    if dialeto == 'postgresql':
        op.execute("UPDATE gabinetes SET assinatura_inicio = CAST(criado_em AS date)")
    else:
        # SQLite (instalação local/desktop) — criado_em já vem como string
        # ISO ("YYYY-MM-DD HH:MM:SS..."); os 10 primeiros caracteres bastam
        # (mesmo padrão já usado em bc9c961bdf45 para data_solicitacao).
        op.execute("UPDATE gabinetes SET assinatura_inicio = substr(criado_em, 1, 10)")

    # Gabinete sem criado_em preenchido (não deveria existir, mas nenhuma
    # migration anterior garantiu isso) usa hoje como início — nunca fica
    # nulo.
    op.execute("UPDATE gabinetes SET assinatura_inicio = CURRENT_DATE WHERE assinatura_inicio IS NULL")

    # Situação segura: todo gabinete já existente entra como ATIVO com
    # vencimento 10 anos à frente — nunca TRIAL/7 dias, que bloquearia
    # gabinetes em produção assim que esta migration roda. Plano
    # permanece NULL (o SUPERADMIN preenche manualmente quando souber o
    # plano real de cada gabinete).
    op.execute("UPDATE gabinetes SET status_assinatura = 'ATIVO' WHERE status_assinatura IS NULL")
    if dialeto == 'postgresql':
        op.execute(
            "UPDATE gabinetes SET assinatura_vencimento = assinatura_inicio + INTERVAL '10 years' "
            "WHERE assinatura_vencimento IS NULL"
        )
    else:
        op.execute(
            "UPDATE gabinetes SET assinatura_vencimento = date(assinatura_inicio, '+10 years') "
            "WHERE assinatura_vencimento IS NULL"
        )

    op.alter_column('gabinetes', 'status_assinatura', nullable=False)
    op.alter_column('gabinetes', 'assinatura_inicio', nullable=False)
    op.alter_column('gabinetes', 'assinatura_vencimento', nullable=False)


def downgrade() -> None:
    op.drop_column('gabinetes', 'assinatura_vencimento')
    op.drop_column('gabinetes', 'assinatura_inicio')
    op.drop_column('gabinetes', 'plano')
    op.drop_column('gabinetes', 'status_assinatura')
