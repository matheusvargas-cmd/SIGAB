import csv
import io
import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.services.eleitor_service import EleitorService

logger = logging.getLogger(__name__)

# Commit a cada N linhas em vez de uma por linha — mesma lógica usada em
# DemandaCsvService/AgendaCsvService, ver comentário lá.
TAMANHO_LOTE = 100

CABECALHO_CSV = [
    "nome",
    "telefone",
    "whatsapp",
    "nascimento",
    "endereco",
    "bairro",
    "cidade",
    "observacoes",
]

# Aliases explícitos (sem fuzzy matching) de cabeçalho de CSV -> campo
# interno aceito por EleitorService.criar(). Cobre tanto os nomes já
# usados no modelo de exportação (CABECALHO_CSV, tudo minúsculo) quanto
# variações reais observadas em CSVs de gabinete (ex.: "Telefone(s)").
# Comparação sempre por igualdade de string após strip().lower() — nunca
# por aproximação/similaridade.
ALIASES_CABECALHO = {
    "nome": "nome",
    "apelido": "apelido",
    "telefone": "telefone",
    "telefone(s)": "telefone",
    "telefones": "telefone",
    "whatsapp": "whatsapp",
    "cpf": "cpf",
    "nascimento": "nascimento",
    "endereco": "endereco",
    "endereço": "endereco",
    "bairro": "bairro",
    "cidade": "cidade",
    "observacoes": "observacoes",
    "observações": "observacoes",
}


class EleitorCsvService:
    @staticmethod
    def exportar(db: Session, gabinete_id: int) -> bytes:
        eleitores = EleitorService.listar_todos(db, gabinete_id)
        buffer = io.StringIO()
        escritor = csv.writer(buffer)
        escritor.writerow(CABECALHO_CSV)
        for eleitor in eleitores:
            escritor.writerow(
                [
                    eleitor.nome,
                    eleitor.telefone or "",
                    eleitor.whatsapp or "",
                    eleitor.nascimento.isoformat() if eleitor.nascimento else "",
                    eleitor.endereco or "",
                    eleitor.bairro or "",
                    eleitor.cidade or "",
                    eleitor.observacoes or "",
                ]
            )
        return buffer.getvalue().encode("utf-8-sig")

    @staticmethod
    def modelo_vazio() -> bytes:
        buffer = io.StringIO()
        csv.writer(buffer).writerow(CABECALHO_CSV)
        return buffer.getvalue().encode("utf-8-sig")

    @staticmethod
    def importar(db: Session, gabinete_id: int, conteudo: bytes) -> dict:
        resultado = {
            "processados": 0,
            "importados": 0,
            "duplicados": 0,
            "erros": [],
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

        delimitador = EleitorCsvService._detectar_delimitador(texto)
        leitor = csv.DictReader(io.StringIO(texto), delimiter=delimitador)

        if not leitor.fieldnames:
            resultado["erro_arquivo"] = "Arquivo CSV sem cabeçalho."
            return resultado

        colunas_brutas = {coluna.strip().lower() for coluna in leitor.fieldnames if coluna}
        if "nome" not in colunas_brutas:
            resultado["erro_arquivo"] = "O CSV precisa ter uma coluna 'nome'."
            return resultado

        for numero, linha in enumerate(leitor, start=2):
            resultado["processados"] += 1
            # Mapeia cada cabeçalho do CSV para o campo interno via alias
            # explícito; colunas sem alias conhecido (ex.: "Genero",
            # "Grupo(s)") são ignoradas aqui — não há campo correspondente
            # no cadastro de eleitor para recebê-las.
            dados: dict[str, str | None] = {}
            for chave, valor in linha.items():
                if chave is None:
                    continue
                campo_interno = ALIASES_CABECALHO.get(chave.strip().lower())
                if campo_interno is None:
                    continue
                dados[campo_interno] = valor.strip() if valor else valor
            try:
                nascimento = EleitorCsvService._converter_data(dados.get("nascimento"))
                EleitorService.criar(
                    db,
                    gabinete_id,
                    nome=dados.get("nome") or "",
                    telefone=dados.get("telefone"),
                    whatsapp=dados.get("whatsapp"),
                    nascimento=nascimento,
                    endereco=dados.get("endereco"),
                    bairro=dados.get("bairro"),
                    cidade=dados.get("cidade"),
                    observacoes=dados.get("observacoes"),
                    apelido=dados.get("apelido"),
                    cpf=dados.get("cpf"),
                )
                resultado["importados"] += 1
            except ValueError as error:
                db.rollback()
                if str(error) == "Cadastro duplicado.":
                    resultado["duplicados"] += 1
                else:
                    resultado["erros"].append((numero, str(error)))
            except Exception:
                db.rollback()
                logger.exception("Erro inesperado ao importar a linha %s do CSV de eleitores.", numero)
                resultado["erros"].append((numero, "Erro inesperado ao processar esta linha."))

        return resultado

    CABECALHO_HISTORICO_OBRIGATORIO = {"Ref Eleitor", "Nome"}

    # Aliases explícitos (sem fuzzy matching) do cabeçalho real exportado
    # pelo Meu Mandato ("listagem-eleitores-...") -> nome canônico já lido
    # por `_mapear_linha_historica`. Comparação por strip().lower(). Um
    # cabeçalho sem alias conhecido (ex.: "Genero", "Grupo(s)", "Estado",
    # "CEP", "Status") é mantido como está — não tem campo correspondente
    # no cadastro de eleitor para recebê-lo, mesma decisão já tomada para
    # o importador genérico.
    ALIASES_CABECALHO_HISTORICO = {
        "ref. eleitor": "Ref Eleitor",
        "nascimento": "Data Nascimento",
        "telefone(s)": "Telefones",
        "logradouro": "Endereço",
        "observações": "Observação",
    }

    @staticmethod
    def importar_historico(db: Session, gabinete_id: int, conteudo: bytes) -> dict:
        """Importa o CSV histórico (formato antigo, ex.: municipe.csv, ou o
        relatório real exportado pelo Meu Mandato, "listagem-eleitores-...").

        Usa `Ref Eleitor` como identificador de idempotência: se já existir
        um eleitor com o mesmo `ref_historico`, a linha é só contada como
        "já existente" e nenhum campo é alterado — mesmo padrão usado por
        `DemandaCsvService`/`AgendaCsvService`. Isso garante que qualquer
        edição manual feita depois da primeira importação nunca é
        sobrescrita por uma reimportação.
        """
        resultado = {
            "processados": 0,
            "novos": 0,
            "existentes": 0,
            "ignorados": 0,
            "erros": [],
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

        delimitador = EleitorCsvService._detectar_delimitador(texto)
        leitor = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
        if not leitor.fieldnames:
            resultado["erro_arquivo"] = "Arquivo CSV sem cabeçalho."
            return resultado

        mapa_cabecalho = EleitorCsvService._normalizar_cabecalho_historico(leitor.fieldnames)
        colunas = set(mapa_cabecalho.values())
        faltantes = EleitorCsvService.CABECALHO_HISTORICO_OBRIGATORIO - colunas
        if faltantes:
            resultado["erro_arquivo"] = (
                f"O CSV precisa ter as colunas {', '.join(sorted(faltantes))}."
            )
            return resultado

        pendentes_no_lote = 0
        for numero, linha_bruta in enumerate(leitor, start=2):
            resultado["processados"] += 1
            linha = {
                mapa_cabecalho[chave]: valor
                for chave, valor in linha_bruta.items()
                if chave is not None
            }

            if not any((valor or "").strip() for valor in linha.values() if valor):
                resultado["ignorados"] += 1
                continue

            ref_historico_bruto = (linha.get("Ref Eleitor") or "").strip()

            try:
                if not ref_historico_bruto:
                    raise ValueError("Ref Eleitor ausente.")

                if (
                    EleitorService.obter_por_ref_historico(db, gabinete_id, ref_historico_bruto)
                    is not None
                ):
                    resultado["existentes"] += 1
                    continue

                # SAVEPOINT por linha — ver comentário equivalente em
                # DemandaCsvService.importar_atendimento_historico.
                with db.begin_nested():
                    dados = EleitorCsvService._mapear_linha_historica(linha)
                    EleitorService.criar(db, gabinete_id, commit=False, **dados)

                resultado["novos"] += 1
                pendentes_no_lote += 1
                if pendentes_no_lote >= TAMANHO_LOTE:
                    db.commit()
                    pendentes_no_lote = 0
            except ValueError as error:
                resultado["erros"].append((numero, str(error)))
            except Exception:
                logger.exception(
                    "Erro inesperado ao importar a linha %s do CSV histórico de eleitores.", numero
                )
                resultado["erros"].append((numero, "Erro inesperado ao processar esta linha."))

        if pendentes_no_lote:
            db.commit()

        return resultado

    @staticmethod
    def _normalizar_cabecalho_historico(fieldnames) -> dict[str, str]:
        """Mapeia cada cabeçalho bruto do CSV histórico para o nome canônico
        interno, usando ALIASES_CABECALHO_HISTORICO (comparação por
        strip().lower(), sem fuzzy matching). Cabeçalho sem alias conhecido
        é mantido como está (já canônico, ex.: "Nome", "Bairro", ou sem
        campo correspondente, ex.: "Genero")."""
        mapa: dict[str, str] = {}
        for bruto in fieldnames:
            if bruto is None:
                continue
            canonico = EleitorCsvService.ALIASES_CABECALHO_HISTORICO.get(bruto.strip().lower())
            mapa[bruto] = canonico or bruto.strip()
        return mapa

    @staticmethod
    def _mapear_linha_historica(linha: dict) -> dict:
        def valor(chave: str) -> str | None:
            bruto = linha.get(chave)
            if bruto is None:
                return None
            limpo = bruto.strip()
            if not limpo or limpo.upper() == "NULL":
                return None
            return limpo

        ref_historico = valor("Ref Eleitor")
        if not ref_historico:
            raise ValueError("Ref Eleitor ausente.")

        nome = valor("Nome")
        if not nome:
            raise ValueError("Nome ausente.")

        nascimento = EleitorCsvService._converter_data(valor("Data Nascimento"))

        partes_endereco = [parte for parte in (valor("Endereço"), valor("Número")) if parte]
        endereco = ", ".join(partes_endereco) if partes_endereco else None
        complemento = valor("Complemento")
        if complemento:
            endereco = f"{endereco} - {complemento}" if endereco else complemento

        return {
            "ref_historico": ref_historico,
            "nome": nome,
            "apelido": valor("Apelido"),
            "cpf": valor("CPF"),
            "endereco": endereco,
            "bairro": valor("Bairro"),
            "cidade": valor("Cidade"),
            "nascimento": nascimento,
            "email": valor("E-mail"),
            "telefone": valor("Telefones"),
            "titulo_eleitor": valor("Titulo eleitor"),
            "zona_eleitoral": valor("Zona eleitoral"),
            "observacoes": valor("Observação"),
        }

    @staticmethod
    def _detectar_delimitador(texto: str) -> str:
        amostra = "\n".join(texto.splitlines()[:5])
        try:
            return csv.Sniffer().sniff(amostra, delimiters=",;").delimiter
        except csv.Error:
            primeira_linha = texto.splitlines()[0] if texto.splitlines() else ""
            return ";" if primeira_linha.count(";") > primeira_linha.count(",") else ","

    @staticmethod
    def _converter_data(valor: str | None) -> date | None:
        if not valor:
            return None
        try:
            return date.fromisoformat(valor)
        except ValueError:
            pass
        try:
            return datetime.strptime(valor, "%d/%m/%Y").date()
        except ValueError:
            raise ValueError("Data de nascimento inválida.")
