# Importar todos os models aqui garante que Base.metadata os conheça antes
# de Base.metadata.create_all()/Alembic rodarem — mesmo um model que ainda
# não tem nenhum service/controller usando ele (ex.: Usuario, Gabinete,
# MembroGabinete nesta fase). É exatamente o problema que o antigo model
# Usuario tinha: nunca era importado em lugar nenhum, então sua tabela
# nunca era criada. main.py importa este pacote antes de create_all().
from app.models.agenda import Agenda
from app.models.categoria import Categoria
from app.models.demanda import Demanda
from app.models.eleitor import Eleitor
from app.models.gabinete import Gabinete
from app.models.membro_gabinete import MembroGabinete
from app.models.subcategoria import Subcategoria
from app.models.usuario import Usuario

__all__ = [
    "Agenda",
    "Categoria",
    "Demanda",
    "Eleitor",
    "Gabinete",
    "MembroGabinete",
    "Subcategoria",
    "Usuario",
]
