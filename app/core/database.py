from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.busca import normalizar
from app.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _registrar_funcoes_sqlite(conexao_dbapi, connection_record):
    # Permite usar normalizar(coluna) diretamente nas consultas, para
    # pesquisa tolerante a acentos e maiúsculas/minúsculas.
    conexao_dbapi.create_function("normalizar", 1, normalizar)


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
