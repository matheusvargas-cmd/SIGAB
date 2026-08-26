import csv
import hashlib
import io
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.services.agenda_service import AgendaService

logger = logging.getLogger(__name__)

# Formato histórico (compromisso.csv, sem coluna de identificador próprio —
# ref_historico é um hash das 7 colunas). Inalterado.
# Commit a cada N linhas em vez de uma por linha — mesma lógica usada em
# DemandaCsvService/EleitorCsvService, ver comentário lá.
TAMANHO_LOTE = 100

CABECALHO_OBRIGATORIO_HISTORICO = {
    "Data inicio",
    "Data fim",
    "Assunto",
    "Descrição",
    "Local",
    "Nome solicitante",
    "Telefone solicitante",
}

# Formato real exportado pelo Meu Mandato (relatório de listagem de
# compromissos): tem identificador próprio ("Ref") mas não tem solicitante.
CABECALHO_OBRIGATORIO_REAL = {"Ref", "Assunto", "Data inicio", "Data fim", "Descrição", "Local"}

# Ordem fixa usada tanto para o hash de idempotência do formato histórico
# quanto para a leitura dos campos — mudar a ordem mudaria os hashes de uma
# importação já feita.
CAMPOS_HASH = [
    "Data inicio",
    "Data fim",
    "Assunto",
    "Descrição",
    "Local",
    "Nome solicitante",
    "Telefone solicitante",
]

# Aliases explícitos (sem fuzzy matching) de cabeçalho real do Meu Mandato ->
# nome canônico já usado pelo formato histórico. Comparação sempre por
# igualdade de string após strip().lower(). Um cabeçalho que já vem no nome
# canônico (ex.: "Assunto", "Descrição", "Local") não precisa de entrada
# aqui — fica de fora do dicionário e é mantido como está.
ALIASES_CABECALHO = {
    "ref.": "Ref",
    "data início": "Data inicio",
    "data fim": "Data fim",
}


class AgendaCsvService:
    @staticmethod
    def importar_compromisso_historico(db: Session, gabinete_id: int, conteudo: bytes) -> dict:
        """Importa o CSV de compromissos, aceitando dois formatos:

        - Histórico (ex.: compromisso.csv): sem identificador próprio, então
          `ref_historico` é um hash SHA-256 determinístico dos 7 campos
          originais da linha (mesmo arquivo → mesmo hash, sempre).
        - Real do Meu Mandato (relatório "listagem-compromissos-..."): tem
          coluna própria de identificador ("Ref"/"Ref."), usada diretamente
          como `ref_historico`; não tem Nome/Telefone do solicitante, então
          esses campos ficam opcionais nesse formato.

        Em nenhum dos dois formatos o compromisso é associado a eleitor ou
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

        delimitador = AgendaCsvService._detectar_delimitador(texto)
        leitor = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
        if not leitor.fieldnames:
            resultado["erro_arquivo"] = "Arquivo CSV sem cabeçalho."
            return resultado

        mapa_cabecalho = AgendaCsvService._normalizar_cabecalho(leitor.fieldnames)
        colunas = set(mapa_cabecalho.values())

        # Se o CSV tem as colunas de solicitante, é o formato histórico
        # completo (validação e comportamento inalterados). Caso contrário,
        # só pode ser o formato real do Meu Mandato — exige "Ref" no lugar.
        formato_historico = {"Nome solicitante", "Telefone solicitante"} <= colunas
        cabecalho_exigido = (
            CABECALHO_OBRIGATORIO_HISTORICO if formato_historico else CABECALHO_OBRIGATORIO_REAL
        )
        faltantes = cabecalho_exigido - colunas
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
            assunto = (linha.get("Assunto") or "").strip()

            try:
                if formato_historico:
                    ref_historico = AgendaCsvService._gerar_ref_historico(linha)
                else:
                    ref_historico = (linha.get("Ref") or "").strip()
                    if not ref_historico:
                        raise ValueError("Ref ausente.")

                if (
                    AgendaService.obter_por_ref_historico(db, gabinete_id, ref_historico)
                    is not None
                ):
                    resultado["existentes"] += 1
                    continue

                dados = AgendaCsvService._mapear_linha(linha)
                if dados["fim_ajustado"]:
                    resultado["fim_invalido_ajustado"] += 1

                # SAVEPOINT por linha — ver comentário equivalente em
                # DemandaCsvService.importar_atendimento_historico.
                with db.begin_nested():
                    AgendaService.criar_historico(
                        db,
                        gabinete_id,
                        titulo=dados["titulo"],
                        descricao=dados["descricao"],
                        local=dados["local"],
                        telefone_contato=dados["telefone_contato"],
                        inicio=dados["inicio"],
                        fim=dados["fim"],
                        status=dados["status"],
                        ref_historico=ref_historico,
                        commit=False,
                    )

                resultado["importados"] += 1
                pendentes_no_lote += 1
                if pendentes_no_lote >= TAMANHO_LOTE:
                    db.commit()
                    pendentes_no_lote = 0
            except ValueError as error:
                resultado["erros"].append((numero, assunto, str(error)))
            except Exception:
                logger.exception(
                    "Erro inesperado ao importar a linha %s do CSV de compromissos.", numero
                )
                resultado["erros"].append(
                    (numero, assunto, "Erro inesperado ao processar esta linha.")
                )

        if pendentes_no_lote:
            db.commit()

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
        """Mapeia cada cabeçalho bruto do CSV para o nome canônico interno
        usando ALIASES_CABECALHO (comparação por strip().lower(), sem fuzzy
        matching). Cabeçalho sem alias conhecido é mantido como está."""
        mapa: dict[str, str] = {}
        for bruto in fieldnames:
            if bruto is None:
                continue
            canonico = ALIASES_CABECALHO.get(bruto.strip().lower())
            mapa[bruto] = canonico or bruto.strip()
        return mapa

    @staticmethod
    def _converter_data_hora(valor_bruto: str) -> datetime:
        """Aceita tanto o formato ISO do histórico (`2025-05-22 17:00:00`)
        quanto o formato do relatório real do Meu Mandato
        (`21/08/2026 15:00`, sem segundos). Sem fuzzy matching — só essas
        duas formas exatas."""
        try:
            return datetime.fromisoformat(valor_bruto)
        except ValueError:
            pass
        try:
            return datetime.strptime(valor_bruto, "%d/%m/%Y %H:%M")
        except ValueError:
            raise ValueError("Data inválida.")

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
            inicio = AgendaCsvService._converter_data_hora(inicio_bruto)
        except ValueError:
            raise ValueError("Data de início inválida.")

        fim = None
        fim_ajustado = False
        fim_bruto = valor("Data fim")
        if fim_bruto:
            try:
                fim_convertido = AgendaCsvService._converter_data_hora(fim_bruto)
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
