import csv
import io
import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.services.eleitor_service import EleitorService

logger = logging.getLogger(__name__)

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


class EleitorCsvService:
    @staticmethod
    def exportar(db: Session) -> bytes:
        eleitores = EleitorService.listar_todos(db)
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
    def importar(db: Session, conteudo: bytes) -> dict:
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

        colunas = {coluna.strip().lower() for coluna in leitor.fieldnames if coluna}
        if "nome" not in colunas:
            resultado["erro_arquivo"] = "O CSV precisa ter uma coluna 'nome'."
            return resultado

        for numero, linha in enumerate(leitor, start=2):
            resultado["processados"] += 1
            dados = {
                chave.strip().lower(): (valor.strip() if valor else valor)
                for chave, valor in linha.items()
                if chave is not None
            }
            try:
                nascimento = EleitorCsvService._converter_data(dados.get("nascimento"))
                EleitorService.criar(
                    db,
                    nome=dados.get("nome") or "",
                    telefone=dados.get("telefone"),
                    whatsapp=dados.get("whatsapp"),
                    nascimento=nascimento,
                    endereco=dados.get("endereco"),
                    bairro=dados.get("bairro"),
                    cidade=dados.get("cidade"),
                    observacoes=dados.get("observacoes"),
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
