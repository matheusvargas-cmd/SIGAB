"""data_solicitacao_e_redefinicao_senha

Bloco 1 — Sistema / Gestão Interna:

  1) Demanda.data_solicitacao — data em que a demanda foi efetivamente
     solicitada (distinta de data_abertura, quando foi cadastrada no
     sistema). Backfill a partir da própria data_abertura (único dado
     equivalente disponível para demandas já existentes, inclusive as de
     origem PUBLICA — preserva coerência com a data de protocolo), depois
     travada para NOT NULL.
  2) redefinicoes_senha — tokens de uso único do fluxo "esqueci minha
     senha" (RedefinicaoSenhaService). Só o hash do token é armazenado,
     nunca o valor em texto puro.

Revision ID: bc9c961bdf45
Revises: c13233079635
Create Date: 2026-09-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc9c961bdf45'
down_revision: Union[str, Sequence[str], None] = 'c13233079635'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1) Demanda.data_solicitacao
    # ----------------------------------------------------------------
    op.add_column('demandas', sa.Column('data_solicitacao', sa.Date(), nullable=True))

    dialeto = op.get_bind().dialect.name
    if dialeto == 'postgresql':
        op.execute("UPDATE demandas SET data_solicitacao = CAST(data_abertura AS date)")
    else:
        # SQLite (instalação local/desktop) não tem CAST(... AS date) —
        # data_abertura já vem como string ISO ("YYYY-MM-DD HH:MM:SS...");
        # os 10 primeiros caracteres bastam.
        op.execute("UPDATE demandas SET data_solicitacao = substr(data_abertura, 1, 10)")

    # Linha sem data_abertura (não deveria existir, coluna é NOT NULL, mas
    # nenhuma migration anterior garantiu isso explicitamente) cairia como
    # NULL acima — usa a data de hoje só para essas, nunca apaga/rejeita
    # a linha.
    op.execute(
        "UPDATE demandas SET data_solicitacao = CURRENT_DATE WHERE data_solicitacao IS NULL"
    )

    op.alter_column('demandas', 'data_solicitacao', nullable=False)

    # ----------------------------------------------------------------
    # 2) redefinicoes_senha
    # ----------------------------------------------------------------
    op.create_table(
        'redefinicoes_senha',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.Column('expira_em', sa.DateTime(), nullable=False),
        sa.Column('usado_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_redefinicoes_senha_usuario_id'), 'redefinicoes_senha', ['usuario_id'], unique=False
    )
    op.create_index(
        op.f('ix_redefinicoes_senha_token_hash'), 'redefinicoes_senha', ['token_hash'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_redefinicoes_senha_token_hash'), table_name='redefinicoes_senha')
    op.drop_index(op.f('ix_redefinicoes_senha_usuario_id'), table_name='redefinicoes_senha')
    op.drop_table('redefinicoes_senha')

    op.drop_column('demandas', 'data_solicitacao')
