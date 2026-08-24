from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.busca import normalizar
from app.core.config import settings

# Alguns detalhes de conexão só existem/fazem sentido num dos dois bancos
# suportados — nada disso é "gambiarra por banco": é a forma correta de
# cada driver, isolada aqui para o resto do código nunca precisar saber
# qual dialeto está em uso (todo o resto do projeto continua chamando
# func.normalizar(coluna) igual, em SQLite ou PostgreSQL).
if settings.is_sqlite:
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,  # evita erro de conexão "morta" após ociosidade
        pool_recycle=1800,  # recicla antes de provedores gerenciados fecharem por idle
        pool_size=5,
        max_overflow=10,
    )


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _registrar_funcoes_sqlite(conexao_dbapi, connection_record):
        # Permite usar normalizar(coluna) diretamente nas consultas, para
        # pesquisa tolerante a acentos e maiúsculas/minúsculas. Em SQLite
        # isso não existe nativamente, então é registrado em Python a cada
        # conexão. Em PostgreSQL o equivalente é a função SQL "normalizar"
        # criada pela migração inicial do Alembic (via extensão unaccent) —
        # já existe no banco, não precisa de nenhum registro aqui.
        conexao_dbapi.create_function("normalizar", 1, normalizar)


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
