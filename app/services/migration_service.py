import logging

from sqlalchemy import inspect, text

from app.core.database import engine

logger = logging.getLogger(__name__)


class MigrationService:
    @staticmethod
    def atualizar_schema_eleitores() -> None:
        inspector = inspect(engine)
        if "eleitores" not in inspector.get_table_names():
            return

        colunas = {coluna["name"] for coluna in inspector.get_columns("eleitores")}
        novas_colunas = {
            "whatsapp": "VARCHAR(30)",
            "nascimento": "DATE",
            "endereco": "VARCHAR(255)",
            "observacoes": "TEXT",
        }

        with engine.begin() as conexao:
            for nome, tipo in novas_colunas.items():
                if nome not in colunas:
                    conexao.execute(text(f"ALTER TABLE eleitores ADD COLUMN {nome} {tipo}"))
                    logger.info("Coluna %s adicionada à tabela eleitores.", nome)

    @staticmethod
    def atualizar_schema_demandas() -> None:
        inspector = inspect(engine)
        if "demandas" not in inspector.get_table_names():
            return

        colunas = {coluna["name"] for coluna in inspector.get_columns("demandas")}
        novas_colunas = {
            "categoria": "VARCHAR(60)",
            "responsavel": "VARCHAR(150)",
            "prazo": "DATE",
            "observacoes_internas": "TEXT",
        }

        with engine.begin() as conexao:
            for nome, tipo in novas_colunas.items():
                if nome not in colunas:
                    conexao.execute(text(f"ALTER TABLE demandas ADD COLUMN {nome} {tipo}"))
                    logger.info("Coluna %s adicionada à tabela demandas.", nome)
