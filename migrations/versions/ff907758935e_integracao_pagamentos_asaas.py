"""integracao_pagamentos_asaas

Fase 2 — Integração de pagamentos com Asaas (Sandbox).

Adiciona a Gabinete três identificadores externos, só para localizar o
cliente/checkout correspondente no Asaas (nunca para decidir validade —
isso continua sendo status_assinatura/plano/assinatura_inicio/
assinatura_vencimento, já existentes desde a Fase 1, intocados aqui):

  - asaas_customer_id
  - asaas_subscription_id
  - asaas_checkout_id

Cria a tabela asaas_webhook_events, usada exclusivamente para
idempotência dos webhooks (o Asaas entrega eventos "at-least-once" — o
mesmo evento pode chegar mais de uma vez). UNIQUE em event_id garante que
o mesmo evento nunca é processado duas vezes, mesmo sob concorrência.

Nenhum dado de cartão é armazenado em nenhuma das duas estruturas.

Revision ID: ff907758935e
Revises: 082b4c3629e0
Create Date: 2026-09-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff907758935e'
down_revision: Union[str, Sequence[str], None] = '082b4c3629e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('gabinetes', sa.Column('asaas_customer_id', sa.String(length=64), nullable=True))
    op.add_column('gabinetes', sa.Column('asaas_subscription_id', sa.String(length=64), nullable=True))
    op.add_column('gabinetes', sa.Column('asaas_checkout_id', sa.String(length=64), nullable=True))

    op.create_table(
        'asaas_webhook_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(length=100), nullable=False),
        sa.Column('event_type', sa.String(length=60), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('payload', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_asaas_webhook_events_event_id'), 'asaas_webhook_events', ['event_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_asaas_webhook_events_event_id'), table_name='asaas_webhook_events')
    op.drop_table('asaas_webhook_events')

    op.drop_column('gabinetes', 'asaas_checkout_id')
    op.drop_column('gabinetes', 'asaas_subscription_id')
    op.drop_column('gabinetes', 'asaas_customer_id')
