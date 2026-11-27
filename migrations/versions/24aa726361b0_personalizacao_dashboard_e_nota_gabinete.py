"""personalizacao_dashboard_e_nota_gabinete

Revision ID: 24aa726361b0
Revises: e4ad3e691df7
Create Date: 2026-11-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24aa726361b0'
down_revision: Union[str, Sequence[str], None] = 'e4ad3e691df7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('gabinetes', sa.Column('dashboard_cards_ativos', sa.Text(), nullable=True))
    op.add_column('gabinetes', sa.Column('nota_dashboard', sa.Text(), nullable=True))
    op.add_column('gabinetes', sa.Column('nota_dashboard_atualizada_em', sa.DateTime(), nullable=True))
    op.add_column('gabinetes', sa.Column('nota_dashboard_atualizado_por_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'gabinetes_nota_dashboard_atualizado_por_id_fkey',
        'gabinetes', 'usuarios',
        ['nota_dashboard_atualizado_por_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'gabinetes_nota_dashboard_atualizado_por_id_fkey', 'gabinetes', type_='foreignkey'
    )
    op.drop_column('gabinetes', 'nota_dashboard_atualizado_por_id')
    op.drop_column('gabinetes', 'nota_dashboard_atualizada_em')
    op.drop_column('gabinetes', 'nota_dashboard')
    op.drop_column('gabinetes', 'dashboard_cards_ativos')
