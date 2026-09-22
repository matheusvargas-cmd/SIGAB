"""idempotencia_financeira_pagamentos_asaas

Correção pós-auditoria da Fase 2 (integração de pagamentos com Asaas).

Cria a tabela asaas_pagamentos_processados — idempotência FINANCEIRA,
distinta e complementar à idempotência de ENTREGA já existente em
asaas_webhook_events (event_id). O Asaas pode descrever a MESMA
cobrança real através de eventos diferentes, cada um com seu próprio
event_id (ex.: PAYMENT_CONFIRMED e depois PAYMENT_RECEIVED para a mesma
cobrança) — deduplicar só por event_id não impede que cada evento,
individualmente novo, dispare uma renovação. UNIQUE em
asaas_identificador_cobranca garante, com o próprio banco (não com um
"select depois insere" vulnerável a corrida), que a mesma cobrança real
nunca renova mais de uma vez.

Revision ID: e4ad3e691df7
Revises: ff907758935e
Create Date: 2026-09-23 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4ad3e691df7'
down_revision: Union[str, Sequence[str], None] = 'ff907758935e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'asaas_pagamentos_processados',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asaas_identificador_cobranca', sa.String(length=64), nullable=False),
        sa.Column('gabinete_id', sa.Integer(), nullable=False),
        sa.Column('asaas_subscription_id', sa.String(length=64), nullable=True),
        sa.Column('event_id', sa.String(length=100), nullable=False),
        sa.Column('plano', sa.String(length=20), nullable=False),
        sa.Column('processado_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['gabinete_id'], ['gabinetes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_asaas_pagamentos_processados_asaas_identificador_cobranca'),
        'asaas_pagamentos_processados',
        ['asaas_identificador_cobranca'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_asaas_pagamentos_processados_asaas_identificador_cobranca'),
        table_name='asaas_pagamentos_processados',
    )
    op.drop_table('asaas_pagamentos_processados')
