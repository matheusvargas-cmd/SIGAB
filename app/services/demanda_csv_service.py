import csv
import io
import logging
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.services.categoria_service import CategoriaService
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService
from app.services.subcategoria_service import SubcategoriaService

logger = logging.getLogger(__name__)

CABECALHO_OBRIGATORIO = {"Ref", "Ref Eleitor", "Data Solicitação", "Descrição", "Status", "Categoria"}

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
}

# Mapeamento aprovado na Etapa 10/12: status histórico -> status SIGAB.
MAPEAMENTO_STATUS: dict[str, str] = {
    "Concluído": "Concluída",
    "aguardando execuçao": "Aguardando terceiros",
    "em analise": "Em andamento",
    "encaminhado p/indicaçao": "Em andamento",
    "recebido": "Aberta",
    "encaminhado p requerimento": "Em andamento",
    "urgencia": "Aberta",
}


class _EleitorNaoEncontrado(Exception):
    pass


class DemandaCsvService:
    @staticmethod
    def importar_atendimento_historico(db: Session, conteudo: bytes) -> dict:
        """Importa o CSV histórico de atendimentos (ex.: atendimento.csv).

        Usa `Ref` como identificador de idempotência (`Demanda.ref_historico`):
        se já existir uma demanda com o mesmo `ref_historico`, a linha é
        contada como "existente" e não é tocada. Só cria a demanda quando o
        `Ref Eleitor` é localizado em `Eleitor.ref_historico` — nunca cria
        eleitor genérico. Categoria e status seguem estritamente o
        mapeamento aprovado; qualquer valor fora dele vira erro, sem
        inventar classificação.
        """
        resultado = {
            "processados": 0,
            "importadas": 0,
            "existentes": 0,
            "sem_eleitor": 0,
            "erros": [],
            "detalhes_sem_eleitor": [],
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

        leitor = csv.DictReader(io.StringIO(texto))
        if not leitor.fieldnames:
            resultado["erro_arquivo"] = "Arquivo CSV sem cabeçalho."
            return resultado

        colunas = {coluna.strip() for coluna in leitor.fieldnames if coluna}
        faltantes = CABECALHO_OBRIGATORIO - colunas
        if faltantes:
            resultado["erro_arquivo"] = (
                f"O CSV precisa ter as colunas {', '.join(sorted(faltantes))}."
            )
            return resultado

        for numero, linha in enumerate(leitor, start=2):
            resultado["processados"] += 1
            ref = (linha.get("Ref") or "").strip()
            ref_eleitor = (linha.get("Ref Eleitor") or "").strip()

            try:
                if not ref:
                    raise ValueError("Ref ausente.")

                if DemandaService.obter_por_ref_historico(db, ref) is not None:
                    resultado["existentes"] += 1
                    continue

                dados = DemandaCsvService._mapear_linha(db, linha)
                DemandaService.criar(
                    db,
                    eleitor_id=str(dados["eleitor_id"]),
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
                )
                resultado["importadas"] += 1
            except _EleitorNaoEncontrado:
                resultado["sem_eleitor"] += 1
                resultado["detalhes_sem_eleitor"].append(
                    (numero, ref, ref_eleitor, "Eleitor não encontrado para este Ref Eleitor.")
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
    def _mapear_linha(db: Session, linha: dict) -> dict:
        def valor(chave: str) -> str | None:
            bruto = linha.get(chave)
            if bruto is None:
                return None
            limpo = bruto.strip()
            if not limpo or limpo.upper() == "NULL":
                return None
            return limpo

        ref_eleitor = valor("Ref Eleitor")
        eleitor = EleitorService.obter_por_ref_historico(db, ref_eleitor) if ref_eleitor else None
        if eleitor is None:
            raise _EleitorNaoEncontrado()

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

        categoria_obj = CategoriaService.obter_por_nome(db, nome_categoria)
        if categoria_obj is None:
            raise ValueError(f"Categoria '{nome_categoria}' não encontrada no cadastro.")

        subcategoria_id = None
        if nome_subcategoria:
            subcategoria_obj = SubcategoriaService.obter_por_nome(
                db, categoria_obj.id, nome_subcategoria
            )
            if subcategoria_obj is not None:
                subcategoria_id = subcategoria_obj.id

        status_bruto = valor("Status")
        if not status_bruto or status_bruto not in MAPEAMENTO_STATUS:
            raise ValueError(f"Status '{status_bruto}' sem mapeamento aprovado.")
        status = MAPEAMENTO_STATUS[status_bruto]

        return {
            "eleitor_id": eleitor.id,
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
