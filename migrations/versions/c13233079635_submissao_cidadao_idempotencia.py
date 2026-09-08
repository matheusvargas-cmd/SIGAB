"""submissao_cidadao_idempotencia

Cria a tabela submissoes_cidadao — trava de idempotência do formulário
público (/cidadao/<public_token>): impede que duas requisições POST quase
simultâneas (duplo clique, corrida) criem duas Demandas a partir do mesmo
envio.

Por que uma tabela (e não só sessão/cookie): a proteção precisa de
atomicidade real sob concorrência — duas requisições concorrentes
enxergam o mesmo cookie/sessão, então uma checagem em memória/sessão
("if token not in session") não serializa nada, as duas passariam. A
UNIQUE constraint em `token` é quem garante isso de verdade: a segunda
requisição a tentar inserir o mesmo token recebe um erro do próprio
banco. Avaliada a alternativa de não usar banco (só sessão) e descartada
exatamente por não cobrir esse caso — ver AtendimentoPublicoService.

Revision ID: c13233079635
Revises: 3cd9d38612a6
Create Date: 2026-09-03 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c13233079635'
down_revision: Union[str, Sequence[str], None] = '3cd9d38612a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'submissoes_cidadao',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('gabinete_id', sa.Integer(), nullable=False),
        sa.Column('demanda_id', sa.Integer(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['demanda_id'], ['demandas.id']),
        sa.ForeignKeyConstraint(['gabinete_id'], ['gabinetes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_submissoes_cidadao_token'), 'submissoes_cidadao', ['token'], unique=True
    )
    op.create_index(
        op.f('ix_submissoes_cidadao_gabinete_id'),
        'submissoes_cidadao',
        ['gabinete_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_submissoes_cidadao_gabinete_id'), table_name='submissoes_cidadao')
    op.drop_index(op.f('ix_submissoes_cidadao_token'), table_name='submissoes_cidadao')
    op.drop_table('submissoes_cidadao')
