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

    CABECALHO_HISTORICO_OBRIGATORIO = {"Ref Eleitor", "Nome"}

    @staticmethod
    def importar_historico(db: Session, conteudo: bytes) -> dict:
        """Importa o CSV histórico do sistema anterior (ex.: municipe.csv).

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

        leitor = csv.DictReader(io.StringIO(texto))
        if not leitor.fieldnames:
            resultado["erro_arquivo"] = "Arquivo CSV sem cabeçalho."
            return resultado

        colunas = {coluna.strip() for coluna in leitor.fieldnames if coluna}
        faltantes = EleitorCsvService.CABECALHO_HISTORICO_OBRIGATORIO - colunas
        if faltantes:
            resultado["erro_arquivo"] = (
                f"O CSV precisa ter as colunas {', '.join(sorted(faltantes))}."
            )
            return resultado

        for numero, linha in enumerate(leitor, start=2):
            resultado["processados"] += 1

            if not any((valor or "").strip() for valor in linha.values() if valor):
                resultado["ignorados"] += 1
                continue

            ref_historico_bruto = (linha.get("Ref Eleitor") or "").strip()

            try:
                if not ref_historico_bruto:
                    raise ValueError("Ref Eleitor ausente.")

                if EleitorService.obter_por_ref_historico(db, ref_historico_bruto) is not None:
                    resultado["existentes"] += 1
                    continue

                dados = EleitorCsvService._mapear_linha_historica(linha)
                EleitorService.criar(db, **dados)
                resultado["novos"] += 1
            except ValueError as error:
                db.rollback()
                resultado["erros"].append((numero, str(error)))
            except Exception:
                db.rollback()
                logger.exception(
                    "Erro inesperado ao importar a linha %s do CSV histórico de eleitores.", numero
                )
                resultado["erros"].append((numero, "Erro inesperado ao processar esta linha."))

        return resultado

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
