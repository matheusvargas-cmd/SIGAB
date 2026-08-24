import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

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
            "apelido": "VARCHAR(100)",
            "email": "VARCHAR(150)",
            "cpf": "VARCHAR(14)",
            "titulo_eleitor": "VARCHAR(12)",
            "zona_eleitoral": "VARCHAR(10)",
            "ref_historico": "VARCHAR(50)",
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
            "categoria_id": "INTEGER",
            "subcategoria_id": "INTEGER",
            "ref_historico": "VARCHAR(50)",
        }

        with engine.begin() as conexao:
            for nome, tipo in novas_colunas.items():
                if nome not in colunas:
                    conexao.execute(text(f"ALTER TABLE demandas ADD COLUMN {nome} {tipo}"))
                    logger.info("Coluna %s adicionada à tabela demandas.", nome)

    @staticmethod
    def atualizar_schema_agenda() -> None:
        inspector = inspect(engine)
        if "agenda" not in inspector.get_table_names():
            return

        colunas = {coluna["name"] for coluna in inspector.get_columns("agenda")}
        novas_colunas = {
            "eleitor_id": "INTEGER",
            "responsavel": "VARCHAR(150)",
            "telefone_contato": "VARCHAR(30)",
            "status": "VARCHAR(30) DEFAULT 'Agendado'",
            "demanda_id": "INTEGER",
            "ref_historico": "VARCHAR(64)",
        }

        with engine.begin() as conexao:
            for nome, tipo in novas_colunas.items():
                if nome not in colunas:
                    conexao.execute(text(f"ALTER TABLE agenda ADD COLUMN {nome} {tipo}"))
                    logger.info("Coluna %s adicionada à tabela agenda.", nome)

    @staticmethod
    def semear_categorias_padrao() -> None:
        """Preserva, na nova tabela de categorias configuráveis, os valores que
        o sistema já usava antes desta estrutura existir: a lista fixa
        histórica de categorias de Demanda e quaisquer valores de
        `Demanda.categoria` já gravados no banco que não estejam nessa lista.
        Idempotente: só insere nomes ainda não presentes (comparação sem
        acento/caixa).
        """
        from app.core.busca import normalizar
        from app.models.categoria import Categoria
        from app.services.demanda_service import CATEGORIAS

        inspector = inspect(engine)
        if "categorias" not in inspector.get_table_names():
            return

        with Session(engine) as sessao:
            existentes = {normalizar(categoria.nome) for categoria in sessao.query(Categoria).all()}

            nomes_a_preservar = list(CATEGORIAS)
            if "demandas" in inspector.get_table_names():
                colunas_demandas = {coluna["name"] for coluna in inspector.get_columns("demandas")}
                if "categoria" in colunas_demandas:
                    resultado = sessao.execute(
                        text("SELECT DISTINCT categoria FROM demandas WHERE categoria IS NOT NULL AND categoria != ''")
                    )
                    for (valor,) in resultado:
                        if valor and valor not in nomes_a_preservar:
                            nomes_a_preservar.append(valor)

            for nome in nomes_a_preservar:
                chave = normalizar(nome)
                if chave not in existentes:
                    sessao.add(Categoria(nome=nome, ativo=True))
                    existentes.add(chave)
                    logger.info("Categoria '%s' semeada a partir dos dados existentes.", nome)

            sessao.commit()

    @staticmethod
    def vincular_categoria_id_demandas() -> None:
        """Liga demandas antigas (que só têm o texto `categoria`) à nova
        tabela de categorias, preenchendo `categoria_id` por nome
        (ignorando acento/caixa). Não altera nem apaga o texto original em
        `categoria` — puramente aditivo, e só toca linhas com
        `categoria_id` ainda nulo, então é seguro rodar repetidamente.
        Depende de `semear_categorias_padrao()` já ter rodado, já que ela
        garante uma Categoria para todo valor histórico de `categoria`.
        """
        from app.core.busca import normalizar
        from app.models.categoria import Categoria
        from app.models.demanda import Demanda

        inspector = inspect(engine)
        if "demandas" not in inspector.get_table_names() or "categorias" not in inspector.get_table_names():
            return

        colunas_demandas = {coluna["name"] for coluna in inspector.get_columns("demandas")}
        if "categoria_id" not in colunas_demandas:
            return

        with Session(engine) as sessao:
            mapa_categorias = {
                normalizar(categoria.nome): categoria.id for categoria in sessao.query(Categoria).all()
            }

            pendentes = (
                sessao.query(Demanda)
                .filter(Demanda.categoria_id.is_(None))
                .filter(Demanda.categoria.isnot(None))
                .all()
            )
            for demanda in pendentes:
                categoria_id = mapa_categorias.get(normalizar(demanda.categoria))
                if categoria_id is not None:
                    demanda.categoria_id = categoria_id

            if pendentes:
                sessao.commit()
                logger.info("%s demanda(s) vinculada(s) à nova tabela de categorias.", len(pendentes))

    @staticmethod
    def semear_categorias_atendimento_historico() -> None:
        """Cria as categorias/subcategorias necessárias para representar os
        atendimentos históricos do atendimento.csv, conforme o mapeamento
        completo aprovado nas Etapas 10/12 (categorias sem correspondência
        direta nas fixas + as subcategorias de todo o mapeamento de
        categoria/subcategoria usado pela importação de Demandas).
        Idempotente: reaproveita categoria/subcategoria já existente com o
        mesmo nome (comparação sem acento/caixa) em vez de duplicar, e nunca
        altera uma categoria/subcategoria já existente.
        """
        from app.core.busca import normalizar
        from app.models.categoria import Categoria
        from app.models.subcategoria import Subcategoria

        inspector = inspect(engine)
        if "categorias" not in inspector.get_table_names() or "subcategorias" not in inspector.get_table_names():
            return

        novas_categorias = ["Saneamento", "Transportes", "Cultura"]
        novas_subcategorias = [
            ("Assistência Social", "Cadeira de Rodas"),
            ("Obras", "Caminhão de terra"),
            ("Saúde", "Autismo"),
            ("Obras", "Manutenção de praças e brinquedos"),
            ("Outros", "Outros"),
            ("Saúde", "Atendimento médico em UBS (clínico geral)"),
            ("Saúde", "Exames de sangue"),
            ("Saúde", "Atendimento médico com especialista"),
            ("Obras", "Asfalto"),
            ("Obras", "Poda de Árvore"),
            ("Assistência Social", "Cesta Básica"),
            ("Assistência Social", "Auxílio Doença"),
            ("Trânsito", "Placas, Lombadas e Sinais"),
            ("Saúde", "Medicamentos"),
            ("Educação", "Vaga em Escolas e Creches"),
            ("Saúde", "Ressonância"),
            ("Trânsito", "Mobilidade urbana (reclamação)"),
            ("Limpeza", "Cata-treco"),
            ("Saúde", "Exames de alta complexidade"),
            ("Saúde", "Vigilância Sanitária"),
            ("Saúde", "Cirurgias de alta complexidade"),
            ("Esporte", "Patrocínio Esportivo"),
            ("Educação", "Merenda"),
            ("Educação", "Instalação de Creches e Escolas"),
        ]

        with Session(engine) as sessao:
            categorias_existentes = {
                normalizar(categoria.nome): categoria for categoria in sessao.query(Categoria).all()
            }

            for nome in novas_categorias:
                if normalizar(nome) not in categorias_existentes:
                    categoria = Categoria(nome=nome, ativo=True)
                    sessao.add(categoria)
                    sessao.flush()
                    categorias_existentes[normalizar(nome)] = categoria
                    logger.info("Categoria '%s' criada (histórico de atendimento).", nome)

            for nome_categoria, nome_subcategoria in novas_subcategorias:
                categoria = categorias_existentes.get(normalizar(nome_categoria))
                if categoria is None:
                    logger.warning(
                        "Categoria '%s' não encontrada; subcategoria '%s' não pôde ser criada.",
                        nome_categoria,
                        nome_subcategoria,
                    )
                    continue

                existentes_sub = {
                    normalizar(subcategoria.nome)
                    for subcategoria in sessao.query(Subcategoria)
                    .filter(Subcategoria.categoria_id == categoria.id)
                    .all()
                }
                if normalizar(nome_subcategoria) not in existentes_sub:
                    sessao.add(
                        Subcategoria(categoria_id=categoria.id, nome=nome_subcategoria, ativo=True)
                    )
                    logger.info(
                        "Subcategoria '%s' criada em '%s' (histórico de atendimento).",
                        nome_subcategoria,
                        nome_categoria,
                    )

            sessao.commit()

    @staticmethod
    def semear_categorias_demandas_reais() -> None:
        """Cria as categorias/subcategorias necessárias para o mapeamento
        aprovado das 18 categorias do CSV real de demandas do gabinete
        (mapeamento categoria-a-categoria confirmado pelo usuário). Reaproveita
        categoria/subcategoria já existente (ex.: Transportes, Esporte /
        Patrocínio Esportivo, Trânsito / Placas, Lombadas e Sinais) — só cria
        o que realmente não existe ainda. Idempotente, mesmo padrão de
        `semear_categorias_atendimento_historico`.
        """
        from app.core.busca import normalizar
        from app.models.categoria import Categoria
        from app.models.subcategoria import Subcategoria

        inspector = inspect(engine)
        if "categorias" not in inspector.get_table_names() or "subcategorias" not in inspector.get_table_names():
            return

        novas_categorias = ["Segurança Pública"]
        novas_subcategorias = [
            ("Obras", "Manutenção de áreas públicas"),
            ("Outros", "Informações na Prefeitura"),
            ("Saúde", "Atendimento médico"),
            ("Educação", "Material Escolar"),
            ("Saúde", "Medicamentos e exames"),
        ]

        with Session(engine) as sessao:
            categorias_existentes = {
                normalizar(categoria.nome): categoria for categoria in sessao.query(Categoria).all()
            }

            for nome in novas_categorias:
                if normalizar(nome) not in categorias_existentes:
                    categoria = Categoria(nome=nome, ativo=True)
                    sessao.add(categoria)
                    sessao.flush()
                    categorias_existentes[normalizar(nome)] = categoria
                    logger.info("Categoria '%s' criada (mapeamento de demandas reais).", nome)

            for nome_categoria, nome_subcategoria in novas_subcategorias:
                categoria = categorias_existentes.get(normalizar(nome_categoria))
                if categoria is None:
                    logger.warning(
                        "Categoria '%s' não encontrada; subcategoria '%s' não pôde ser criada.",
                        nome_categoria,
                        nome_subcategoria,
                    )
                    continue

                existentes_sub = {
                    normalizar(subcategoria.nome)
                    for subcategoria in sessao.query(Subcategoria)
                    .filter(Subcategoria.categoria_id == categoria.id)
                    .all()
                }
                if normalizar(nome_subcategoria) not in existentes_sub:
                    sessao.add(
                        Subcategoria(categoria_id=categoria.id, nome=nome_subcategoria, ativo=True)
                    )
                    logger.info(
                        "Subcategoria '%s' criada em '%s' (mapeamento de demandas reais).",
                        nome_subcategoria,
                        nome_categoria,
                    )

            sessao.commit()

    @staticmethod
    def relaxar_eleitor_obrigatorio_demandas() -> None:
        """A partir desta etapa, uma Demanda pode existir sem eleitor
        vinculado — o sistema de origem (Meu Mandato) permite "Ref. eleitor"
        vazio ou não encontrado (ex.: demandas do próprio gabinete, sem
        munícipe associado). O schema original declarava `eleitor_id` como
        NOT NULL; SQLite não tem um `ALTER TABLE` que remova essa
        constraint, então quando necessário a tabela é reconstruída pelo
        procedimento padrão do próprio SQLite para isso: renomeia a tabela
        atual, recria "demandas" a partir do model atual (já com
        `eleitor_id` nullable), copia os dados linha a linha preservando
        todas as colunas, descarta a tabela renomeada. Idempotente: só
        executa se a coluna ainda estiver NOT NULL (banco novo já nasce
        nullable via `Base.metadata.create_all`, então não entra aqui).
        """
        from app.models.demanda import Demanda

        inspector = inspect(engine)
        if "demandas" not in inspector.get_table_names():
            return

        colunas = {coluna["name"]: coluna for coluna in inspector.get_columns("demandas")}
        coluna_eleitor = colunas.get("eleitor_id")
        if coluna_eleitor is None or coluna_eleitor["nullable"]:
            return

        nomes_colunas = ", ".join(colunas.keys())
        with engine.begin() as conexao:
            conexao.execute(text("ALTER TABLE demandas RENAME TO demandas_migracao_antiga"))
            Demanda.__table__.create(bind=conexao)
            conexao.execute(
                text(
                    f"INSERT INTO demandas ({nomes_colunas}) "
                    f"SELECT {nomes_colunas} FROM demandas_migracao_antiga"
                )
            )
            conexao.execute(text("DROP TABLE demandas_migracao_antiga"))
        logger.info(
            "Coluna demandas.eleitor_id relaxada para permitir NULL (demanda sem eleitor vinculado)."
        )
