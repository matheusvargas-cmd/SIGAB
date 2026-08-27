"""superadmin_gabinete_responsavel

Revision ID: 514ce097e4cd
Revises: 11cde0c50e85
Create Date: 2026-08-27 11:28:30.474864

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '514ce097e4cd'
down_revision: Union[str, Sequence[str], None] = '11cde0c50e85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('gabinetes', sa.Column('responsavel', sa.String(length=150), nullable=True))
    # server_default=false() é obrigatório aqui: sem ele, adicionar uma
    # coluna NOT NULL numa tabela `usuarios` que já tem linhas falha (o
    # Postgres não sabe que valor colocar nas linhas existentes). Nenhum
    # usuário existente vira SUPERADMIN por causa disso — o default é
    # exatamente "false", a mesma coisa que o campo já significava antes de
    # existir (ninguém era superadmin). Promover alguém continua exigindo
    # uma ação explícita via scripts/promover_superadmin.py.
    op.add_column(
        'usuarios',
        sa.Column('super_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('usuarios', 'super_admin')
    op.drop_column('gabinetes', 'responsavel')
