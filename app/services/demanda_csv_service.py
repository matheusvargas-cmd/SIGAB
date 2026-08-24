import csv
import io
import logging
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.services.categoria_service import CategoriaService
from app.services.demanda_service import STATUS_OPCOES, DemandaService
from app.services.eleitor_service import EleitorService
from app.services.subcategoria_service import SubcategoriaService

logger = logging.getLogger(__name__)

CABECALHO_OBRIGATORIO = {"Ref", "Ref Eleitor", "Data Solicitação", "Descrição", "Status", "Categoria"}

# Aliases explícitos (sem fuzzy matching) de cabeçalho real de CSV de
# gabinete -> cabeçalho canônico usado internamente por este arquivo (o
# mesmo já usado pelo CSV histórico original: "Ref", "Ref Eleitor",
# "Data Solicitação"). Comparação sempre por igualdade de string após
# strip().lower() — nunca por aproximação/similaridade. Um cabeçalho que
# já vem no nome canônico (ex.: "Ref") não precisa de entrada aqui: fica
# de fora do dicionário e é mantido como está.
ALIASES_CABECALHO = {
    "ref. atendimento": "Ref",
    "ref. eleitor": "Ref Eleitor",
    "data de solicitação": "Data Solicitação",
}

TITULO_MAXIMO = 150

# Mapeamento aprovado na Etapa 10/12: categoria histórica (texto exato do
# CSV) -> (Categoria SIGAB, Subcategoria SIGAB ou None).
MAPEAMENTO_CATEGORIA: dict[str, tuple[str, str | None]] = {
    "Outros": ("Outros", "Outros"),
    "Atendimento médico em ubs clinico geral": ("Saúde", "Atendimento médico em UBS (clínico geral)"),
    "Exames de sangue": ("Saúde", "Exames de sangue"),
    "atendimento medico com especialista": ("Saúde", "Atendimento médico com especialista"),
    "Limpeza": ("Limpeza", None),
    "Iluminação": ("Iluminação", None),
    "Asfalto": ("Obras", "Asfalto"),
    "Poda de Árvore": ("Obras", "Poda de Árvore"),
    "Cestas Básicas": ("Assistência Social", "Cesta Básica"),
    "Auxilio Doença": ("Assistência Social", "Auxílio Doença"),
    "Placas, Lombadas e Sinais": ("Trânsito", "Placas, Lombadas e Sinais"),
    "Medicamentos": ("Saúde", "Medicamentos"),
    "Vaga em Escolas e Creches": ("Educação", "Vaga em Escolas e Creches"),
    "Ressonância": ("Saúde", "Ressonância"),
    "mobilidade urbana reclamacao": ("Trânsito", "Mobilidade urbana (reclamação)"),
    "Cata Treco": ("Limpeza", "Cata-treco"),
    "Moradia": ("Habitação", None),
    "exames de alta complexicidade": ("Saúde", "Exames de alta complexidade"),
    "Vigilância Sanitária": ("Saúde", "Vigilância Sanitária"),
    "Cirurgias alta complexicidade": ("Saúde", "Cirurgias de alta complexidade"),
    "Patrocínio Esportivo": ("Esporte", "Patrocínio Esportivo"),
    "Merenda": ("Educação", "Merenda"),
    "Instalação de Creches e Escolas": ("Educação", "Instalação de Creches e Escolas"),
    "Saneamento, Água e Esgoto": ("Saneamento", None),
    "Transportes solicitacao de viagens": ("Transportes", None),
    "Patrocínio Cultural": ("Cultura", None),
    "CADEIRA DE RODAS": ("Assistência Social", "Cadeira de Rodas"),
    "Solicitação de caminhão de terra": ("Obras", "Caminhão de terra"),
    "autismo": ("Saúde", "Autismo"),
    "manutencao de pracinha e brinquedos": ("Obras", "Manutenção de praças e brinquedos"),
    # Mapeamento aprovado nesta etapa: categorias do CSV real de demandas do
    # gabinete (230 registros) sem correspondência exata no mapeamento acima.
    "Manutenção de áreas públicas": ("Obras", "Manutenção de áreas públicas"),
    "Patrocínio Esportivo e Incentivo ao Esporte": ("Esporte", "Patrocínio Esportivo"),
    "Informações na Prefeitura": ("Outros", "Informações na Prefeitura"),
    "Transporte": ("Transportes", None),
    "Segurança Pública": ("Segurança Pública", None),
    "Atendimento médico": ("Saúde", "Atendimento médico"),
    "Material Escolar": ("Educação", "Material Escolar"),
    "Medicamentos e exames": ("Saúde", "Medicamentos e exames"),
}

# Mapeamento aprovado na Etapa 10/12: status histórico (texto exato do CSV
# antigo atendimento.csv) -> vocabulário legado do SIGAB (usado antes da
# adoção dos 7 status oficiais). Mantido sem alteração — é só a primeira
# metade da tradução; a segunda metade (legado -> oficial) é
# MAPEAMENTO_STATUS_LEGADO_PARA_OFICIAL, logo abaixo.
MAPEAMENTO_STATUS: dict[str, str] = {
    "Concluído": "Concluída",
    "aguardando execuçao": "Aguardando terceiros",
    "em analise": "Em andamento",
    "encaminhado p/indicaçao": "Em andamento",
    "recebido": "Aberta",
    "encaminhado p requerimento": "Em andamento",
    "urgencia": "Aberta",
}

# Mapeamento aprovado nesta etapa: vocabulário legado do SIGAB -> vocabulário
# oficial atual (7 status). Só usado para converter o resultado de
# MAPEAMENTO_STATUS acima durante a importação histórica — nenhuma demanda é
# gravada no banco com o vocabulário legado; não existem dois vocabulários
# em paralelo.
MAPEAMENTO_STATUS_LEGADO_PARA_OFICIAL: dict[str, str] = {
    "Aberta": "Protocolado",
    "Em andamento": "Em andamento",
    "Aguardando terceiros": "A fazer",
    "Concluída": "Concluído",
    "Cancelada": "Cancelada",
}


class DemandaCsvService:
    @staticmethod
    def importar_atendimento_historico(db: Session, gabinete_id: int, conteudo: bytes) -> dict:
        """Importa o CSV de atendimentos (histórico ou real do Meu Mandato).

        Usa `Ref` como identificador de idempotência (`Demanda.ref_historico`):
        se já existir uma demanda com o mesmo `ref_historico`, a linha é
        contada como "existente" e não é tocada.

        Vínculo com eleitor (`Ref Eleitor` -> `Eleitor.ref_historico`) NÃO é
        obrigatório: o sistema de origem (Meu Mandato) permite demanda sem
        eleitor (ex.: "Ref. eleitor" vazio, ou "Eleitor" = nome do próprio
        gabinete). Se `Ref Eleitor` vier vazio, ou não for encontrado em
        `Eleitor.ref_historico`, a demanda é importada normalmente com
        `eleitor_id` nulo — nunca é bloqueada nem vira erro — e é contada à
        parte em "sem_vinculo" (nunca cria eleitor genérico a partir da
        coluna "Eleitor", que pode não representar uma pessoa).

        Categoria e status seguem estritamente o mapeamento aprovado;
        qualquer valor fora dele vira erro, sem inventar classificação.
        """
        resultado = {
            "processados": 0,
            "importadas": 0,
            "vinculadas": 0,
            "sem_vinculo": 0,
            "existentes": 0,
            "erros": [],
            "detalhes_sem_vinculo": [],
            "erro_arquivo": None,
        }

        try:
            texto = conteudo.decode("utf-8-sig")
        except UnicodeDecodeError:
            resultado["erro_arquivo"] = (
                "Não foi possível ler o arquivo como texto UTF-8. "
                "Salve o CSV em formato UTF-8 e tente novamente."
            )
            return resultado

        if not texto.strip():
            resultado["erro_arquivo"] = "Arquivo CSV vazio."
            return resultado

        delimitador = DemandaCsvService._detectar_delimitador(texto)
        leitor = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
        if not leitor.fieldnames:
            resultado["erro_arquivo"] = "Arquivo CSV sem cabeçalho."
            return resultado

        mapa_cabecalho = DemandaCsvService._normalizar_cabecalho(leitor.fieldnames)
        colunas = set(mapa_cabecalho.values())
        faltantes = CABECALHO_OBRIGATORIO - colunas
        if faltantes:
            resultado["erro_arquivo"] = (
                f"O CSV precisa ter as colunas {', '.join(sorted(faltantes))}."
            )
            return resultado

        for numero, linha_bruta in enumerate(leitor, start=2):
            resultado["processados"] += 1
            linha = {
                mapa_cabecalho[chave]: valor
                for chave, valor in linha_bruta.items()
                if chave is not None
            }
            ref = (linha.get("Ref") or "").strip()
            ref_eleitor = (linha.get("Ref Eleitor") or "").strip()

            try:
                if not ref:
                    raise ValueError("Ref ausente.")

                if DemandaService.obter_por_ref_historico(db, gabinete_id, ref) is not None:
                    resultado["existentes"] += 1
                    continue

                dados = DemandaCsvService._mapear_linha(db, gabinete_id, linha)
                DemandaService.criar(
                    db,
                    gabinete_id,
                    eleitor_id=(str(dados["eleitor_id"]) if dados["eleitor_id"] else None),
                    titulo=dados["titulo"],
                    descricao=dados["descricao"],
                    categoria_id=str(dados["categoria_id"]),
                    subcategoria_id=(
                        str(dados["subcategoria_id"]) if dados["subcategoria_id"] else None
                    ),
                    status=dados["status"],
                    prioridade="Normal",
                    secretaria=dados["secretaria"],
                    ref_historico=ref,
                    data_abertura=dados["data_abertura"],
                    fechar_automaticamente=False,
                    eleitor_obrigatorio=False,
                )
                resultado["importadas"] += 1
                if dados["eleitor_id"]:
                    resultado["vinculadas"] += 1
                else:
                    resultado["sem_vinculo"] += 1
                    resultado["detalhes_sem_vinculo"].append(
                        (numero, ref, ref_eleitor, dados["vinculo_motivo"])
                    )
            except ValueError as error:
                db.rollback()
                resultado["erros"].append((numero, ref, ref_eleitor, str(error)))
            except Exception:
                db.rollback()
                logger.exception(
                    "Erro inesperado ao importar a linha %s do CSV de atendimentos.", numero
                )
                resultado["erros"].append(
                    (numero, ref, ref_eleitor, "Erro inesperado ao processar esta linha.")
                )

        return resultado

    @staticmethod
    def _detectar_delimitador(texto: str) -> str:
        """CSVs históricos usam vírgula; o relatório real do Meu Mandato usa
        ponto e vírgula. Detecta pela amostra do cabeçalho, sem depender de
        um formato fixo — mesma lógica já usada por EleitorCsvService."""
        amostra = "\n".join(texto.splitlines()[:5])
        try:
            return csv.Sniffer().sniff(amostra, delimiters=",;").delimiter
        except csv.Error:
            primeira_linha = texto.splitlines()[0] if texto.splitlines() else ""
            return ";" if primeira_linha.count(";") > primeira_linha.count(",") else ","

    @staticmethod
    def _normalizar_cabecalho(fieldnames) -> dict[str, str]:
        """Mapeia cada cabeçalho bruto do CSV (exatamente como veio no
        arquivo) para o nome canônico interno, usando ALIASES_CABECALHO
        (comparação por strip().lower(), sem fuzzy matching). Cabeçalhos
        sem alias conhecido são mantidos como estão (ex.: "Origem",
        "Escritório", "Data Cadastro" do CSV histórico original, ou o
        próprio cabeçalho já canônico como "Ref") — não são lidos adiante,
        então não precisam de alias."""
        mapa: dict[str, str] = {}
        for bruto in fieldnames:
            if bruto is None:
                continue
            canonico = ALIASES_CABECALHO.get(bruto.strip().lower())
            mapa[bruto] = canonico or bruto.strip()
        return mapa

    @staticmethod
    def _mapear_linha(db: Session, gabinete_id: int, linha: dict) -> dict:
        def valor(chave: str) -> str | None:
            bruto = linha.get(chave)
            if bruto is None:
                return None
            limpo = bruto.strip()
            if not limpo or limpo.upper() == "NULL":
                return None
            return limpo

        ref_eleitor = valor("Ref Eleitor")
        eleitor_id = None
        vinculo_motivo = None
        if not ref_eleitor:
            vinculo_motivo = "Ref Eleitor vazio."
        else:
            eleitor = EleitorService.obter_por_ref_historico(db, gabinete_id, ref_eleitor)
            if eleitor is None:
                vinculo_motivo = "Eleitor não encontrado para este Ref Eleitor."
            else:
                eleitor_id = eleitor.id

        descricao = linha.get("Descrição") or ""
        descricao_normalizada = descricao.strip()
        if not descricao_normalizada:
            raise ValueError("Descrição ausente.")
        titulo = DemandaCsvService._gerar_titulo(descricao)

        data_bruta = valor("Data Solicitação")
        if not data_bruta:
            raise ValueError("Data de solicitação ausente.")
        try:
            data_abertura = datetime.combine(date.fromisoformat(data_bruta), time.min)
        except ValueError:
            raise ValueError("Data de solicitação inválida.")

        categoria_bruta = valor("Categoria")
        if not categoria_bruta or categoria_bruta not in MAPEAMENTO_CATEGORIA:
            raise ValueError(f"Categoria '{categoria_bruta}' sem mapeamento aprovado.")
        nome_categoria, nome_subcategoria = MAPEAMENTO_CATEGORIA[categoria_bruta]

        categoria_obj = CategoriaService.obter_por_nome(db, gabinete_id, nome_categoria)
        if categoria_obj is None:
            raise ValueError(f"Categoria '{nome_categoria}' não encontrada no cadastro.")

        subcategoria_id = None
        if nome_subcategoria:
            subcategoria_obj = SubcategoriaService.obter_por_nome(
                db, gabinete_id, categoria_obj.id, nome_subcategoria
            )
            if subcategoria_obj is not None:
                subcategoria_id = subcategoria_obj.id

        status_bruto = valor("Status")
        if not status_bruto:
            raise ValueError("Status ausente.")
        if status_bruto in STATUS_OPCOES:
            # CSV real do gabinete: a coluna Status já vem no vocabulário
            # oficial (Protocolado, A fazer, Em andamento, Em análise, Não
            # realizado, Concluído, Cancelada) — usa direto, sem tradução.
            status = status_bruto
        elif status_bruto in MAPEAMENTO_STATUS:
            # atendimento.csv do sistema anterior: texto bruto -> vocabulário
            # legado -> vocabulário oficial (MAPEAMENTO_STATUS_LEGADO_PARA_OFICIAL).
            status_legado = MAPEAMENTO_STATUS[status_bruto]
            status = MAPEAMENTO_STATUS_LEGADO_PARA_OFICIAL[status_legado]
        else:
            raise ValueError(f"Status '{status_bruto}' sem mapeamento aprovado.")

        return {
            "eleitor_id": eleitor_id,
            "vinculo_motivo": vinculo_motivo,
            "titulo": titulo,
            "descricao": descricao_normalizada,
            "categoria_id": categoria_obj.id,
            "subcategoria_id": subcategoria_id,
            "status": status,
            "secretaria": valor("Secretaria"),
            "data_abertura": data_abertura,
        }

    @staticmethod
    def _gerar_titulo(descricao: str) -> str:
        for linha_texto in descricao.split("\n"):
            candidata = linha_texto.strip()
            if candidata:
                return candidata[:TITULO_MAXIMO]
        return descricao.strip()[:TITULO_MAXIMO]
