"""fundacao_atendimento_ao_cidadao

Fundação técnica do futuro módulo de Atendimento ao Cidadão
(/cidadao/<public_token>) — nenhuma rota pública, upload ou WhatsApp de
demanda é criado aqui, só o schema:

  1) Gabinete.public_token — identificador público de 6 caracteres,
     gerado para cada gabinete já existente, único, nunca o id numérico.
  2) Demanda.origem ("INTERNA"/"PUBLICA") — demandas existentes viram
     "INTERNA".
  3) demanda_anexos — metadado de arquivo (o binário vai para storage
     externo, futuramente Cloudflare R2; nenhuma integração é feita aqui).
  4) historico_demandas — trilha de mudança de status; usuario_id
     nullable (atendimento público não tem usuário autenticado).
  5) Eleitor.cpf_normalizado + unicidade condicional (gabinete_id +
     cpf_normalizado) — só criada se os dados existentes não tiverem
     conflito; se houver, a constraint é pulada e os conflitos são
     impressos no log da migration, sem apagar/alterar nada.

Revision ID: 3cd9d38612a6
Revises: d7852c6d0c1c
Create Date: 2026-08-28 15:00:00.000000

"""
import re
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cd9d38612a6'
down_revision: Union[str, Sequence[str], None] = 'd7852c6d0c1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Copiado de app/services/gabinete_service.py (não importado) — mesma
# razão de 11cde0c50e85: uma migration deve continuar fazendo exatamente
# a mesma coisa mesmo que o código evolua depois.
ALFABETO_TOKEN_PUBLICO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TAMANHO_TOKEN_PUBLICO = 6


def _gerar_token_unico(existentes: set) -> str:
    while True:
        token = "".join(
            secrets.choice(ALFABETO_TOKEN_PUBLICO) for _ in range(TAMANHO_TOKEN_PUBLICO)
        )
        if token not in existentes:
            existentes.add(token)
            return token


def upgrade() -> None:
    conexao = op.get_bind()

    # ------------------------------------------------------------------
    # 1) Gabinete.public_token
    # ------------------------------------------------------------------
    op.add_column('gabinetes', sa.Column('public_token', sa.String(length=6), nullable=True))

    gabinetes = sa.table(
        "gabinetes", sa.column("id", sa.Integer), sa.column("public_token", sa.String)
    )
    tokens_existentes: set = set()
    for (gabinete_id,) in conexao.execute(sa.select(gabinetes.c.id)):
        token = _gerar_token_unico(tokens_existentes)
        conexao.execute(
            gabinetes.update().where(gabinetes.c.id == gabinete_id).values(public_token=token)
        )

    op.alter_column('gabinetes', 'public_token', nullable=False)
    op.create_index(
        op.f('ix_gabinetes_public_token'), 'gabinetes', ['public_token'], unique=True
    )

    # ------------------------------------------------------------------
    # 2) Demanda.origem — server_default cobre as linhas existentes no
    #    mesmo ALTER TABLE (mesmo padrão de 514ce097e4cd/super_admin).
    # ------------------------------------------------------------------
    op.add_column(
        'demandas',
        sa.Column('origem', sa.String(length=20), nullable=False, server_default='INTERNA'),
    )

    # ------------------------------------------------------------------
    # 3) demanda_anexos — só metadado; conteúdo binário fica fora do
    #    Postgres (storage externo, ver docstring do model).
    # ------------------------------------------------------------------
    op.create_table(
        'demanda_anexos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('demanda_id', sa.Integer(), nullable=False),
        sa.Column('gabinete_id', sa.Integer(), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('nome_original', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=True),
        sa.Column('tamanho_bytes', sa.Integer(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.Column('arquivo_disponivel', sa.Boolean(), nullable=False),
        sa.Column('excluido_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['demanda_id'], ['demandas.id']),
        sa.ForeignKeyConstraint(['gabinete_id'], ['gabinetes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_demanda_anexos_demanda_id'), 'demanda_anexos', ['demanda_id'], unique=False
    )
    op.create_index(
        op.f('ix_demanda_anexos_gabinete_id'), 'demanda_anexos', ['gabinete_id'], unique=False
    )

    # ------------------------------------------------------------------
    # 4) historico_demandas
    # ------------------------------------------------------------------
    op.create_table(
        'historico_demandas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('demanda_id', sa.Integer(), nullable=False),
        sa.Column('gabinete_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('status_anterior', sa.String(length=40), nullable=True),
        sa.Column('status_novo', sa.String(length=40), nullable=False),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['demanda_id'], ['demandas.id']),
        sa.ForeignKeyConstraint(['gabinete_id'], ['gabinetes.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_historico_demandas_demanda_id'),
        'historico_demandas',
        ['demanda_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_historico_demandas_gabinete_id'),
        'historico_demandas',
        ['gabinete_id'],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 5) Eleitor.cpf_normalizado + unicidade condicional
    # ------------------------------------------------------------------
    op.add_column('eleitores', sa.Column('cpf_normalizado', sa.String(length=20), nullable=True))

    eleitores = sa.table(
        "eleitores",
        sa.column("id", sa.Integer),
        sa.column("gabinete_id", sa.Integer),
        sa.column("cpf", sa.String),
        sa.column("cpf_normalizado", sa.String),
    )
    linhas = conexao.execute(
        sa.select(eleitores.c.id, eleitores.c.gabinete_id, eleitores.c.cpf)
    ).all()

    normalizados: dict = {}
    for eleitor_id, gabinete_id, cpf in linhas:
        cpf_normalizado = (re.sub(r"\D", "", cpf) or None) if cpf else None
        normalizados[eleitor_id] = cpf_normalizado
        if cpf_normalizado:
            conexao.execute(
                eleitores.update()
                .where(eleitores.c.id == eleitor_id)
                .values(cpf_normalizado=cpf_normalizado)
            )

    # Conflito = mesmo gabinete_id (não-NULL) + mesmo cpf_normalizado em
    # mais de um eleitor. Linhas com gabinete_id NULL são ignoradas aqui de
    # propósito: um índice único trata cada NULL como distinto dos demais
    # (padrão SQL, vale tanto em PostgreSQL quanto em SQLite), então duas
    # linhas gabinete_id=NULL com o mesmo CPF nunca violariam o índice —
    # não faz sentido barrar a constraint por causa delas.
    grupos: dict = {}
    for eleitor_id, gabinete_id, _cpf in linhas:
        cpf_normalizado = normalizados[eleitor_id]
        if not cpf_normalizado or gabinete_id is None:
            continue
        chave = (gabinete_id, cpf_normalizado)
        grupos.setdefault(chave, []).append(eleitor_id)

    duplicados = {chave: ids for chave, ids in grupos.items() if len(ids) > 1}

    if duplicados:
        print("=" * 78)
        print(
            f"AVISO (migration {revision}): constraint de unicidade de CPF "
            f"NÃO foi criada — {len(duplicados)} conflito(s) encontrado(s):"
        )
        for (gabinete_id, cpf_normalizado), ids in sorted(duplicados.items()):
            print(
                f"  gabinete_id={gabinete_id} cpf_normalizado={cpf_normalizado} "
                f"eleitor_ids={ids}"
            )
        print(
            "Nenhum registro foi apagado ou alterado além do backfill de "
            "cpf_normalizado. Saneie manualmente e crie a constraint numa "
            "migration futura."
        )
        print("=" * 78)
    else:
        op.execute(
            "CREATE UNIQUE INDEX ix_eleitores_gabinete_cpf_normalizado "
            "ON eleitores (gabinete_id, cpf_normalizado) "
            "WHERE cpf_normalizado IS NOT NULL"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_eleitores_gabinete_cpf_normalizado")
    op.drop_column('eleitores', 'cpf_normalizado')

    op.drop_index(op.f('ix_historico_demandas_gabinete_id'), table_name='historico_demandas')
    op.drop_index(op.f('ix_historico_demandas_demanda_id'), table_name='historico_demandas')
    op.drop_table('historico_demandas')

    op.drop_index(op.f('ix_demanda_anexos_gabinete_id'), table_name='demanda_anexos')
    op.drop_index(op.f('ix_demanda_anexos_demanda_id'), table_name='demanda_anexos')
    op.drop_table('demanda_anexos')

    op.drop_column('demandas', 'origem')

    op.drop_index(op.f('ix_gabinetes_public_token'), table_name='gabinetes')
    op.drop_column('gabinetes', 'public_token')
