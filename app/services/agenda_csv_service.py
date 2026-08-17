import csv
import hashlib
import io
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.services.agenda_service import AgendaService

logger = logging.getLogger(__name__)

CABECALHO_OBRIGATORIO = {
    "Data inicio",
    "Data fim",
    "Assunto",
    "Descrição",
    "Local",
    "Nome solicitante",
    "Telefone solicitante",
}

# Ordem fixa usada tanto para o hash de idempotência quanto para a leitura
# dos campos — mudar a ordem mudaria os hashes de uma importação já feita.
CAMPOS_HASH = [
    "Data inicio",
    "Data fim",
    "Assunto",
    "Descrição",
    "Local",
    "Nome solicitante",
    "Telefone solicitante",
]


class AgendaCsvService:
    @staticmethod
    def importar_compromisso_historico(db: Session, conteudo: bytes) -> dict:
        """Importa o CSV histórico de compromissos (ex.: compromisso.csv).

        O arquivo não tem um identificador próprio, então `ref_historico` é
        um hash SHA-256 determinístico dos 7 campos originais da linha
        (mesmo arquivo → mesmo hash, sempre). Nunca associa eleitor nem
        demanda — todo compromisso importado nasce com `eleitor_id` e
        `demanda_id` nulos, e nunca aciona a sincronização Demanda→Agenda.
        """
        resultado = {
            "processados": 0,
            "importados": 0,
            "existentes": 0,
            "fim_invalido_ajustado": 0,
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
        faltantes = CABECALHO_OBRIGATORIO - colunas
        if faltantes:
            resultado["erro_arquivo"] = (
                f"O CSV precisa ter as colunas {', '.join(sorted(faltantes))}."
            )
            return resultado

        for numero, linha in enumerate(leitor, start=2):
            resultado["processados"] += 1
            assunto = (linha.get("Assunto") or "").strip()

            try:
                ref_historico = AgendaCsvService._gerar_ref_historico(linha)

                if AgendaService.obter_por_ref_historico(db, ref_historico) is not None:
                    resultado["existentes"] += 1
                    continue

                dados = AgendaCsvService._mapear_linha(linha)
                if dados["fim_ajustado"]:
                    resultado["fim_invalido_ajustado"] += 1

                AgendaService.criar_historico(
                    db,
                    titulo=dados["titulo"],
                    descricao=dados["descricao"],
                    local=dados["local"],
                    telefone_contato=dados["telefone_contato"],
                    inicio=dados["inicio"],
                    fim=dados["fim"],
                    status=dados["status"],
                    ref_historico=ref_historico,
                )
                resultado["importados"] += 1
            except ValueError as error:
                db.rollback()
                resultado["erros"].append((numero, assunto, str(error)))
            except Exception:
                db.rollback()
                logger.exception(
                    "Erro inesperado ao importar a linha %s do CSV de compromissos.", numero
                )
                resultado["erros"].append(
                    (numero, assunto, "Erro inesperado ao processar esta linha.")
                )

        return resultado

    @staticmethod
    def _gerar_ref_historico(linha: dict) -> str:
        partes = []
        for campo in CAMPOS_HASH:
            bruto = linha.get(campo)
            valor = (bruto or "").strip()
            if valor.upper() == "NULL":
                valor = ""
            partes.append(valor)
        composto = "|".join(partes)
        return hashlib.sha256(composto.encode("utf-8")).hexdigest()

    @staticmethod
    def _mapear_linha(linha: dict) -> dict:
        def valor(chave: str) -> str | None:
            bruto = linha.get(chave)
            if bruto is None:
                return None
            limpo = bruto.strip()
            if not limpo or limpo.upper() == "NULL":
                return None
            return limpo

        titulo = valor("Assunto")
        if not titulo:
            raise ValueError("Assunto ausente.")

        inicio_bruto = valor("Data inicio")
        if not inicio_bruto:
            raise ValueError("Data de início ausente.")
        try:
            inicio = datetime.fromisoformat(inicio_bruto)
        except ValueError:
            raise ValueError("Data de início inválida.")

        fim = None
        fim_ajustado = False
        fim_bruto = valor("Data fim")
        if fim_bruto:
            try:
                fim_convertido = datetime.fromisoformat(fim_bruto)
            except ValueError:
                raise ValueError("Data de término inválida.")
            if fim_convertido <= inicio:
                fim_ajustado = True
            else:
                fim = fim_convertido

        descricao_original = valor("Descrição")
        nome_solicitante = valor("Nome solicitante")
        if nome_solicitante:
            linha_solicitante = f"Solicitante: {nome_solicitante}"
            descricao = (
                f"{descricao_original}\n\n{linha_solicitante}"
                if descricao_original
                else linha_solicitante
            )
        else:
            descricao = descricao_original

        status = "Realizado" if inicio < datetime.now() else "Agendado"

        return {
            "titulo": titulo,
            "descricao": descricao,
            "local": valor("Local"),
            "telefone_contato": valor("Telefone solicitante"),
            "inicio": inicio,
            "fim": fim,
            "fim_ajustado": fim_ajustado,
            "status": status,
        }
