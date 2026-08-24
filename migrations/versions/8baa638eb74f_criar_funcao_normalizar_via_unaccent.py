"""criar funcao normalizar via unaccent

Cria, só em PostgreSQL, a função SQL "normalizar(text)" usada em toda busca
tolerante a acento/caixa do sistema (func.normalizar(coluna) em
eleitor_service.py, demanda_service.py, agenda_service.py). Em SQLite o
equivalente é registrado em Python a cada conexão (ver app/core/database.py)
— nunca passa por migração, por isso esta migração não faz nada lá (e não
deveria: SQLite não tem CREATE EXTENSION).

Revision ID: 8baa638eb74f
Revises: da30883281a3
Create Date: 2026-08-24 12:51:24.104533

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8baa638eb74f'
down_revision: Union[str, Sequence[str], None] = 'da30883281a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION normalizar(texto text)
        RETURNS text AS $$
            SELECT lower(unaccent(texto))
        $$ LANGUAGE SQL IMMUTABLE STRICT
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP FUNCTION IF EXISTS normalizar(text)")
    # A extensão unaccent não é removida no downgrade: pode ser usada por
    # outras partes do banco além desta função.
