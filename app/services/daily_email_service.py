import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.models.gabinete import Gabinete
from app.services.agenda_service import AgendaService
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService
from app.services.email_sender_service import EmailNaoConfiguradoError, EmailSenderService
from app.services.gabinete_service import GabineteService
from app.services.whatsapp_link_service import WhatsappLinkService

logger = logging.getLogger(__name__)

FUSO_OPERACIONAL = ZoneInfo("America/Sao_Paulo")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class DailyEmailService:
    """Orquestra o e-mail diário de UM gabinete por vez — monta os dados
    (reaproveitando EleitorService/AgendaService/DemandaService, sempre
    filtrados por gabinete_id), gera os links de WhatsApp, renderiza o
    HTML/texto e manda para EmailSenderService enviar. Não duplica nenhuma
    regra de negócio de Agenda/Eleitores/Demandas — só lê o que esses
    serviços já expõem."""

    ASSUNTO = "Gabinete 360 — Agenda e informações de hoje"

    @staticmethod
    def hoje_operacional() -> date:
        """"Hoje" no fuso operacional do gabinete (America/Sao_Paulo), não
        no fuso do servidor — o Render normalmente roda em UTC, e
        date.today() ali pode já estar num dia diferente do horário real
        de Brasília, principalmente à noite."""
        return datetime.now(FUSO_OPERACIONAL).date()

    @staticmethod
    def _formatar_horario_compromisso(inicio: datetime, fim: datetime | None) -> str:
        texto = inicio.strftime("%H:%M")
        if fim:
            texto += f" às {fim.strftime('%H:%M')}"
        return texto

    @staticmethod
    def _mensagem_aniversario(nome_eleitor: str, gabinete: Gabinete) -> str:
        primeiro_nome = (nome_eleitor or "").strip().split(" ")[0] or nome_eleitor
        identificacao = gabinete.responsavel or gabinete.nome
        return (
            f"Olá, {primeiro_nome}! Passando para desejar um feliz aniversário! 🎉 "
            "Que seu dia seja muito especial, com muita saúde, paz e realizações. "
            f"Um grande abraço do Gabinete {identificacao}!"
        )

    @staticmethod
    def montar_dados(db: Session, gabinete: Gabinete, data: date) -> dict:
        """Monta exatamente o conteúdo do e-mail para este gabinete e esta
        data — sem enviar nada. Usado tanto pelo envio real quanto (se
        precisar no futuro) por uma pré-visualização."""
        gabinete_id = gabinete.id

        compromissos_do_dia = AgendaService.relatorio_por_periodo(
            db, gabinete_id, data_inicio=data, data_fim=data
        )
        compromissos = [
            {
                "horario": DailyEmailService._formatar_horario_compromisso(c.inicio, c.fim),
                "titulo": c.titulo,
                "local": c.local,
            }
            for c in compromissos_do_dia
        ]

        aniversariantes_eleitores = EleitorService.listar_aniversariantes_hoje(db, gabinete_id, data)
        aniversariantes = []
        for eleitor in aniversariantes_eleitores:
            mensagem = DailyEmailService._mensagem_aniversario(eleitor.nome, gabinete)
            telefone_para_link = eleitor.whatsapp or eleitor.telefone
            aniversariantes.append(
                {
                    "nome": eleitor.nome,
                    "telefone_exibicao": telefone_para_link or None,
                    "mensagem": mensagem,
                    "whatsapp_link": WhatsappLinkService.gerar_link(telefone_para_link, mensagem),
                }
            )

        demandas_atrasadas = [
            {
                "titulo": d.titulo,
                "eleitor_nome": d.eleitor.nome if d.eleitor else None,
                "prazo_formatado": d.prazo.strftime("%d/%m/%Y") if d.prazo else "-",
            }
            for d in DemandaService.listar_atrasadas(db, gabinete_id, data)
        ]
        demandas_vencendo_hoje = [
            {"titulo": d.titulo, "eleitor_nome": d.eleitor.nome if d.eleitor else None}
            for d in DemandaService.listar_vencendo_hoje(db, gabinete_id, data)
        ]

        return {
            "assunto": DailyEmailService.ASSUNTO,
            "gabinete_nome": gabinete.responsavel or gabinete.nome,
            "data_formatada": data.strftime("%d/%m/%Y"),
            "compromissos": compromissos,
            "aniversariantes": aniversariantes,
            "demandas_atrasadas": demandas_atrasadas,
            "demandas_vencendo_hoje": demandas_vencendo_hoje,
        }

    @staticmethod
    def _renderizar_html(dados: dict) -> str:
        return templates.get_template("email/diario.html").render(dados)

    @staticmethod
    def _renderizar_texto(dados: dict) -> str:
        linhas = [dados["assunto"], f"{dados['gabinete_nome']} — {dados['data_formatada']}", ""]

        linhas.append("AGENDA DE HOJE")
        if dados["compromissos"]:
            for c in dados["compromissos"]:
                linha = f"- {c['horario']} — {c['titulo']}"
                if c["local"]:
                    linha += f" ({c['local']})"
                linhas.append(linha)
        else:
            linhas.append("Nenhum compromisso agendado para hoje.")
        linhas.append("")

        linhas.append("ANIVERSARIANTES DE HOJE")
        if dados["aniversariantes"]:
            for a in dados["aniversariantes"]:
                linhas.append(f"- {a['nome']}" + (f" ({a['telefone_exibicao']})" if a["telefone_exibicao"] else ""))
                linhas.append(f"  Mensagem: {a['mensagem']}")
                if a["whatsapp_link"]:
                    linhas.append(f"  WhatsApp: {a['whatsapp_link']}")
        else:
            linhas.append("Nenhum aniversariante hoje.")
        linhas.append("")

        if dados["demandas_atrasadas"] or dados["demandas_vencendo_hoje"]:
            linhas.append("DEMANDAS QUE PRECISAM DE ATENÇÃO")
            for d in dados["demandas_atrasadas"]:
                linhas.append(f"- ATRASADA: {d['titulo']} (prazo {d['prazo_formatado']})")
            for d in dados["demandas_vencendo_hoje"]:
                linhas.append(f"- VENCE HOJE: {d['titulo']}")
            linhas.append("")

        linhas.append("Gabinete 360 — Gestão Inteligente de Gabinetes")
        return "\n".join(linhas)

    @staticmethod
    def enviar_diario(db: Session, gabinete_id: int, data: date | None = None, forcar: bool = False) -> dict:
        """Envia o e-mail diário deste gabinete para esta data. Idempotente:
        se já foi enviado com sucesso para esta data, não envia de novo a
        menos que forcar=True (usado só pelo botão manual do SUPERADMIN,
        para permitir reenviar durante um teste)."""
        data = data or DailyEmailService.hoje_operacional()

        gabinete = db.get(Gabinete, gabinete_id)
        if gabinete is None:
            return {"status": "erro", "motivo": "Gabinete não encontrado."}

        if not gabinete.email_institucional:
            return {"status": "sem_email", "motivo": "Gabinete sem e-mail institucional configurado."}

        if not forcar and GabineteService.ja_enviou_diario_hoje(db, gabinete_id, data):
            return {"status": "ja_enviado", "motivo": f"E-mail diário de {data:%d/%m/%Y} já enviado."}

        dados = DailyEmailService.montar_dados(db, gabinete, data)
        html = DailyEmailService._renderizar_html(dados)
        texto = DailyEmailService._renderizar_texto(dados)

        try:
            EmailSenderService.enviar(gabinete.email_institucional, dados["assunto"], texto, html)
        except EmailNaoConfiguradoError as error:
            return {"status": "smtp_nao_configurado", "motivo": str(error)}
        except Exception:
            logger.exception("Falha ao enviar e-mail diário do gabinete %s.", gabinete_id)
            return {"status": "erro", "motivo": "Falha ao enviar e-mail — ver logs."}

        GabineteService.registrar_envio_diario(db, gabinete_id, data)
        return {"status": "enviado", "motivo": f"E-mail diário enviado para {gabinete.email_institucional}."}

    @staticmethod
    def enviar_diario_todos_os_gabinetes(db: Session, data: date | None = None) -> list[dict]:
        """Usado pelo job externo (POST /jobs/enviar-diario) — percorre
        todos os gabinetes ATIVOS, um de cada vez, cada chamada
        completamente isolada por gabinete_id (nunca uma consulta global de
        Eleitor/Demanda/Agenda misturando gabinetes)."""
        data = data or DailyEmailService.hoje_operacional()
        resultados = []
        gabinetes = GabineteService.listar_todos(db)
        for gabinete in gabinetes:
            if not gabinete.ativo:
                continue
            resultado = DailyEmailService.enviar_diario(db, gabinete.id, data)
            resultado["gabinete_id"] = gabinete.id
            resultado["gabinete_nome"] = gabinete.nome
            resultados.append(resultado)
        return resultados
