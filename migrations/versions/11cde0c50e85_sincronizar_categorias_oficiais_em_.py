"""sincronizar_categorias_oficiais_em_gabinetes_existentes

Revision ID: 11cde0c50e85
Revises: a2352dddc5bd
Create Date: 2026-08-26 13:13:56.708305

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11cde0c50e85'
down_revision: Union[str, Sequence[str], None] = 'a2352dddc5bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mesma lista de app/services/demanda_service.py:CATEGORIAS — mantida
# copiada aqui (não importada) de propósito: uma migration deve continuar
# fazendo exatamente a mesma coisa mesmo que a lista no código evolua no
# futuro (nova categoria adicionada não deve reescrever a história desta
# migration). Nenhuma dependência de app.* nem de MigrationService — só
# SQLAlchemy Core sobre as tabelas já existentes, para não depender do
# estado dos models Python no momento em que a migration rodar.
CATEGORIAS_OFICIAIS = [
    "Saúde",
    "Educação",
    "Obras",
    "Iluminação",
    "Limpeza",
    "Trânsito",
    "Esporte",
    "Assistência Social",
    "Habitação",
    "Outros",
    "Saneamento",
    "Transportes",
    "Cultura",
]


def upgrade() -> None:
    """Garante, para cada gabinete já existente, uma linha de Categoria para
    cada nome em CATEGORIAS_OFICIAIS — sem duplicar a que já existir
    (comparação por nome normalizado: espaços nas pontas ignorados,
    maiúscula/minúscula ignorada) e sem tocar em nenhuma categoria, demanda,
    eleitor ou usuário já cadastrado. Puramente aditiva: só faz INSERT.

    Corrige o mesmo problema que scripts/criar_primeiro_admin.py resolve
    para gabinetes novos (via MigrationService.semear_categorias_para_gabinete)
    — aqui para os gabinetes que já existiam antes de "Saneamento",
    "Transportes" e "Cultura" entrarem na lista oficial.
    """
    conexao = op.get_bind()

    gabinetes = sa.table("gabinetes", sa.column("id", sa.Integer))
    categorias = sa.table(
        "categorias",
        sa.column("id", sa.Integer),
        sa.column("gabinete_id", sa.Integer),
        sa.column("nome", sa.String),
        sa.column("ativo", sa.Boolean),
    )

    gabinete_ids = [linha.id for linha in conexao.execute(sa.select(gabinetes.c.id))]

    for gabinete_id in gabinete_ids:
        existentes = {
            (nome or "").strip().lower()
            for (nome,) in conexao.execute(
                sa.select(categorias.c.nome).where(categorias.c.gabinete_id == gabinete_id)
            )
        }
        for nome in CATEGORIAS_OFICIAIS:
            chave = nome.strip().lower()
            if chave in existentes:
                continue
            conexao.execute(
                categorias.insert().values(gabinete_id=gabinete_id, nome=nome, ativo=True)
            )
            existentes.add(chave)


def downgrade() -> None:
    """No-op deliberado: não remove nenhuma categoria.

    Uma categoria criada por esta migration pode já estar em uso por
    demandas reais (Demanda.categoria_id) assim que o upgrade roda — apagar
    a linha de Categoria no downgrade quebraria essa referência (ou exigiria
    decidir o que fazer com as demandas já vinculadas, o que esta migration
    não tem informação suficiente para decidir com segurança). Reverter
    schema é sempre seguro aqui; reverter dado que passou a ser usado, não.
    """
    pass
