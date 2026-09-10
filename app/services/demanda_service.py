import logging
from datetime import date, datetime, time, timedelta
from math import ceil
from typing import Any

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.busca import normalizar
from app.models.categoria import Categoria
from app.models.demanda import Demanda
from app.models.demanda_anexo import DemandaAnexo
from app.models.eleitor import Eleitor
from app.models.historico_demanda import HistoricoDemanda
from app.models.submissao_cidadao import SubmissaoCidadao
from app.models.subcategoria import Subcategoria
from app.services.agenda_service import AgendaService
from app.services.demanda_anexo_service import DemandaAnexoService
from app.services.historico_demanda_service import HistoricoDemandaService
from app.services.storage_service import obter_storage_service

logger = logging.getLogger(__name__)

POR_PAGINA = 20

MENSAGEM_FALHA_EXCLUSAO_ANEXO = (
    "Não foi possível concluir a exclusão porque um ou mais anexos não puderam ser removidos "
    "do armazenamento. Nenhum dado da demanda foi excluído. Tente novamente ou solicite "
    "suporte técnico."
)


class FalhaExclusaoAnexoError(Exception):
    """Levantada por DemandaService.excluir() quando existem anexos com
    arquivo ainda no storage e pelo menos um deles não pôde ser removido
    do R2 (ou o storage não está configurado neste ambiente). Nunca
    carrega detalhe de infraestrutura na mensagem — só a mensagem
    amigável definida em MENSAGEM_FALHA_EXCLUSAO_ANEXO."""
TITULO_MINIMO_CARACTERES = 5

CATEGORIAS = [
    "Saúde",
    "Educação",
    "Obras",
    "Iluminação",
    "Limpeza",
    "Trânsito",
    "Esporte",
    "Assistência Social",
    "Habitação",
    "Outros",
    "Saneamento",
    "Transportes",
    "Cultura",
]
STATUS_OPCOES = [
    "Protocolado",
    "A fazer",
    "Em andamento",
    "Em análise",
    "Não realizado",
    "Concluído",
    "Cancelada",
]
PRIORIDADE_OPCOES = ["Baixa", "Normal", "Alta", "Urgente"]

# Status considerados finalizados para fins de "pendência em aberto"
# (atrasadas, prazo próximo, em andamento): uma demanda Cancelada não é
# "concluída" (contar_concluidas checa só "Concluído"), mas também não é
# mais um trabalho pendente — por isso entra aqui, e não em contar_concluidas.
STATUS_FINALIZADOS = ("Concluído", "Não realizado", "Cancelada")

_ORDEM_PRIORIDADE = case(
    (Demanda.prioridade == "Urgente", 0),
    (Demanda.prioridade == "Alta", 1),
    (Demanda.prioridade == "Normal", 2),
    (Demanda.prioridade == "Baixa", 3),
    else_=4,
)

# Colunas que a tela de demandas permite ordenar clicando no cabeçalho
# (DemandaService.listar, ordenar_por) — nenhuma coluna fora desta lista é
# aceita, mesmo que exista no model (evita expor ordenação por coisas como
# observacoes_internas via query string adivinhada).
COLUNAS_ORDENAVEIS = {
    "data_solicitacao": Demanda.data_solicitacao,
    "prazo": Demanda.prazo,
    "status": Demanda.status,
    "prioridade": _ORDEM_PRIORIDADE,
}


class DemandaService:
    """Toda consulta/escrita aqui é sempre filtrada por gabinete_id — ver
    app/core/contexto.py. Nunca aceitar gabinete_id vindo do cliente:
    sempre o gabinete_id do ContextoSessao autenticado."""

    @staticmethod
    def _consulta_filtrada(
        gabinete_id: int,
        pesquisa: str | None,
        origem: str | None,
        status: str | None,
        atrasada: bool,
    ):
        """Monta a base de `select(Demanda)` com todos os filtros da tela
        de demandas aplicados (gabinete, origem, status, atrasada,
        pesquisa) — sem ORDER BY nem LIMIT/OFFSET, que cada chamador
        decide por conta própria. Único lugar onde esses filtros são
        escritos: tanto listar() (paginado) quanto
        listar_todos_filtrados() (impressão, sem paginação) reaproveitam
        exatamente a mesma lógica, nunca duas versões que podem divergir
        silenciosamente. outerjoin (não join): uma demanda sem eleitor
        vinculado (eleitor_id nulo — CSV real do Meu Mandato permite isso)
        precisa continuar aparecendo na listagem normal, não só quando tem
        eleitor."""
        consulta = (
            select(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .outerjoin(Eleitor, Demanda.eleitor_id == Eleitor.id)
            .options(joinedload(Demanda.eleitor))
        )

        # Filtro opcional por origem (INTERNA/PUBLICA) — sempre no banco,
        # nunca em Python: evita trazer registros a mais só para
        # descartá-los depois, e mantém total/paginação coerentes com o
        # que de fato foi filtrado.
        if origem:
            consulta = consulta.where(Demanda.origem == origem)

        if status and status in STATUS_OPCOES:
            consulta = consulta.where(Demanda.status == status)

        # "Atrasada" nunca é um status gravado — é sempre calculado na hora
        # (prazo vencido + status ainda não finalizado), mesma regra de
        # contar_atrasadas()/listar_atrasadas() abaixo. Filtrar assim,
        # sempre no banco, é o que permite este filtro conviver com
        # paginação/ordenação sem duas fontes de verdade divergentes.
        if atrasada:
            hoje = date.today()
            consulta = consulta.where(
                and_(
                    Demanda.prazo.isnot(None),
                    Demanda.prazo < hoje,
                    Demanda.status.notin_(STATUS_FINALIZADOS),
                )
            )

        if pesquisa and pesquisa.strip():
            termo = f"%{normalizar(pesquisa.strip())}%"
            consulta = consulta.where(
                or_(
                    func.normalizar(Eleitor.nome).like(termo),
                    func.normalizar(Demanda.titulo).like(termo),
                    func.normalizar(Demanda.categoria).like(termo),
                    func.normalizar(Demanda.status).like(termo),
                    func.normalizar(Demanda.responsavel).like(termo),
                    func.normalizar(Eleitor.cidade).like(termo),
                )
            )

        return consulta

    @staticmethod
    def _ordenar(consulta, ordenar_por: str | None, ordenar_direcao: str):
        # Ordenação por cabeçalho clicável (tela de demandas) — só as
        # colunas em COLUNAS_ORDENAVEIS, nunca uma coluna arbitrária vinda
        # da query string. Sem ordenar_por (ou valor não reconhecido),
        # mantém o critério padrão de sempre: prioridade, depois abertura.
        coluna_ordenacao = COLUNAS_ORDENAVEIS.get(ordenar_por or "")
        if coluna_ordenacao is not None:
            direcao = coluna_ordenacao.desc() if ordenar_direcao == "desc" else coluna_ordenacao.asc()
            # Desempate por id: sem isso, duas linhas com o mesmo valor na
            # coluna ordenada (ex.: mesmo prazo) poderiam mudar de posição
            # entre páginas/execuções diferentes da mesma consulta.
            return consulta.order_by(direcao, Demanda.id.desc())
        return consulta.order_by(_ORDEM_PRIORIDADE, Demanda.data_abertura)

    @staticmethod
    def listar(
        db: Session,
        gabinete_id: int,
        pesquisa: str | None = None,
        pagina: int = 1,
        origem: str | None = None,
        status: str | None = None,
        atrasada: bool = False,
        ordenar_por: str | None = None,
        ordenar_direcao: str = "asc",
    ) -> tuple[list[Demanda], int, int]:
        consulta = DemandaService._consulta_filtrada(gabinete_id, pesquisa, origem, status, atrasada)
        total_registros = db.scalar(
            select(func.count()).select_from(consulta.with_only_columns(Demanda.id).subquery())
        ) or 0
        total_paginas = max(1, ceil(total_registros / POR_PAGINA))
        pagina_atual = min(max(1, pagina), total_paginas)

        consulta = DemandaService._ordenar(consulta, ordenar_por, ordenar_direcao)
        consulta = consulta.limit(POR_PAGINA).offset((pagina_atual - 1) * POR_PAGINA)
        demandas = list(db.scalars(consulta).unique().all())
        return demandas, pagina_atual, total_paginas

    @staticmethod
    def listar_todos_filtrados(
        db: Session,
        gabinete_id: int,
        pesquisa: str | None = None,
        origem: str | None = None,
        status: str | None = None,
        atrasada: bool = False,
        ordenar_por: str | None = None,
        ordenar_direcao: str = "asc",
    ) -> list[Demanda]:
        """Mesmos filtros e mesma ordenação de listar() (reaproveita
        _consulta_filtrada/_ordenar — nunca uma segunda implementação que
        possa divergir), mas sem LIMIT/OFFSET: usado exclusivamente pela
        impressão do relatório (app/modules/demandas/controller.py), que
        precisa do conjunto completo que corresponde ao filtro, nunca
        apenas a página exibida na tela."""
        consulta = DemandaService._consulta_filtrada(gabinete_id, pesquisa, origem, status, atrasada)
        consulta = DemandaService._ordenar(consulta, ordenar_por, ordenar_direcao)
        return list(db.scalars(consulta).unique().all())

    @staticmethod
    def calcular_atraso(demanda: Demanda, hoje: date | None = None) -> int | None:
        """Situação "atrasada" nunca é um status gravado no banco — é
        sempre calculado a partir da data atual (mesma regra usada por
        contar_atrasadas()/listar_atrasadas()/o filtro `atrasada` de
        listar()). Devolve None quando a demanda NÃO está atrasada (sem
        prazo, prazo ainda não vencido, ou já concluída/cancelada/não
        realizada) — nesse caso o chamador simplesmente não mostra nada de
        atraso. Quando atrasada, devolve os dias de atraso (sempre >= 1)."""
        referencia = hoje or date.today()
        if (
            demanda.prazo is None
            or demanda.status in STATUS_FINALIZADOS
            or demanda.prazo >= referencia
        ):
            return None
        return (referencia - demanda.prazo).days

    @staticmethod
    def obter_por_id(db: Session, gabinete_id: int, demanda_id: int) -> Demanda | None:
        demanda = db.get(Demanda, demanda_id)
        if demanda is None or demanda.gabinete_id != gabinete_id:
            return None
        return demanda

    @staticmethod
    def obter_por_ref_historico(db: Session, gabinete_id: int, ref_historico: str) -> Demanda | None:
        return db.scalar(
            select(Demanda).where(
                Demanda.gabinete_id == gabinete_id, Demanda.ref_historico == ref_historico
            )
        )

    @staticmethod
    def listar_eleitores_para_selecao(db: Session, gabinete_id: int) -> list[Eleitor]:
        consulta = select(Eleitor).where(Eleitor.gabinete_id == gabinete_id).order_by(Eleitor.nome)
        return list(db.scalars(consulta).all())

    @staticmethod
    def contar_em_andamento(db: Session, gabinete_id: int) -> int:
        consulta = (
            select(func.count())
            .select_from(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .where(Demanda.status.notin_(STATUS_FINALIZADOS))
        )
        return db.scalar(consulta) or 0

    @staticmethod
    def contar_concluidas(db: Session, gabinete_id: int) -> int:
        consulta = (
            select(func.count())
            .select_from(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .where(Demanda.status == "Concluído")
        )
        return db.scalar(consulta) or 0

    @staticmethod
    def contar_total(db: Session, gabinete_id: int) -> int:
        consulta = select(func.count()).select_from(Demanda).where(Demanda.gabinete_id == gabinete_id)
        return db.scalar(consulta) or 0

    @staticmethod
    def contar_atrasadas(db: Session, gabinete_id: int) -> int:
        hoje = date.today()
        consulta = (
            select(func.count())
            .select_from(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .where(Demanda.prazo.isnot(None))
            .where(Demanda.prazo < hoje)
            .where(Demanda.status.notin_(STATUS_FINALIZADOS))
        )
        return db.scalar(consulta) or 0

    @staticmethod
    def contar_prazo_proximo(db: Session, gabinete_id: int, dias: int = 7) -> int:
        hoje = date.today()
        limite = hoje + timedelta(days=dias)
        consulta = (
            select(func.count())
            .select_from(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .where(Demanda.prazo.isnot(None))
            .where(Demanda.prazo >= hoje)
            .where(Demanda.prazo <= limite)
            .where(Demanda.status.notin_(STATUS_FINALIZADOS))
        )
        return db.scalar(consulta) or 0

    @staticmethod
    def listar_atrasadas(db: Session, gabinete_id: int, data: date | None = None) -> list[Demanda]:
        """Mesma regra de contar_atrasadas() acima (prazo vencido, status
        ainda não finalizado), só que devolvendo os registros — usado pelo
        e-mail diário (app/services/daily_email_service.py). `data` opcional
        para permitir passar o "hoje" já calculado em America/Sao_Paulo."""
        referencia = data or date.today()
        consulta = (
            select(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .where(Demanda.prazo.isnot(None))
            .where(Demanda.prazo < referencia)
            .where(Demanda.status.notin_(STATUS_FINALIZADOS))
            .options(joinedload(Demanda.eleitor))
            .order_by(Demanda.prazo)
        )
        return list(db.scalars(consulta).unique().all())

    @staticmethod
    def listar_vencendo_hoje(db: Session, gabinete_id: int, data: date | None = None) -> list[Demanda]:
        """Demandas com prazo exatamente na data de referência, ainda não
        finalizadas — mesmo critério de status de contar_prazo_proximo()."""
        referencia = data or date.today()
        consulta = (
            select(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .where(Demanda.prazo == referencia)
            .where(Demanda.status.notin_(STATUS_FINALIZADOS))
            .options(joinedload(Demanda.eleitor))
            .order_by(Demanda.titulo)
        )
        return list(db.scalars(consulta).unique().all())

    @staticmethod
    def listar_recentes(db: Session, gabinete_id: int, limite: int = 5) -> list[Demanda]:
        consulta = (
            select(Demanda)
            .where(Demanda.gabinete_id == gabinete_id)
            .options(joinedload(Demanda.eleitor))
            .order_by(Demanda.data_abertura.desc())
            .limit(limite)
        )
        return list(db.scalars(consulta).unique().all())

    @staticmethod
    def relatorio_por_status(
        db: Session,
        gabinete_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        categoria: str | None = None,
        prioridade: str | None = None,
    ) -> list[dict]:
        consulta = (
            select(Demanda.status, func.count())
            .where(Demanda.gabinete_id == gabinete_id)
            .group_by(Demanda.status)
        )
        consulta = DemandaService._aplicar_filtros_relatorio(
            consulta, data_inicio, data_fim, categoria=categoria, prioridade=prioridade
        )
        contagem = dict(db.execute(consulta).all())
        return [
            {"rotulo": status, "quantidade": contagem.get(status, 0)}
            for status in STATUS_OPCOES
        ]

    @staticmethod
    def relatorio_por_categoria(
        db: Session,
        gabinete_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        status: str | None = None,
        prioridade: str | None = None,
    ) -> list[dict]:
        consulta = (
            select(Demanda.categoria_id, func.count())
            .where(Demanda.gabinete_id == gabinete_id)
            .group_by(Demanda.categoria_id)
        )
        consulta = DemandaService._aplicar_filtros_relatorio(
            consulta, data_inicio, data_fim, status=status, prioridade=prioridade
        )
        contagem = dict(db.execute(consulta).all())
        categorias = db.scalars(
            select(Categoria).where(Categoria.gabinete_id == gabinete_id).order_by(Categoria.nome)
        ).all()
        resultado = [
            {"rotulo": categoria.nome, "quantidade": contagem.get(categoria.id, 0)}
            for categoria in categorias
        ]
        resultado.sort(key=lambda item: item["quantidade"], reverse=True)
        return resultado

    @staticmethod
    def relatorio_por_periodo(
        db: Session,
        gabinete_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        status: str | None = None,
        categoria: str | None = None,
    ) -> list[dict]:
        consulta = select(Demanda.data_abertura).where(Demanda.gabinete_id == gabinete_id)
        consulta = DemandaService._aplicar_filtros_relatorio(
            consulta, data_inicio, data_fim, status=status, categoria=categoria
        )
        contagem: dict[str, int] = {}
        for (data_abertura,) in db.execute(consulta).all():
            if not data_abertura:
                continue
            chave = data_abertura.strftime("%Y-%m")
            contagem[chave] = contagem.get(chave, 0) + 1
        return [
            {"rotulo": chave, "quantidade": quantidade}
            for chave, quantidade in sorted(contagem.items())
        ]

    @staticmethod
    def relatorio_por_eleitor(db: Session, gabinete_id: int, eleitor_id: int) -> list[Demanda]:
        consulta = (
            select(Demanda)
            .where(Demanda.gabinete_id == gabinete_id, Demanda.eleitor_id == eleitor_id)
            .order_by(Demanda.data_abertura.desc())
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def _aplicar_filtros_relatorio(
        consulta,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        categoria: str | None = None,
        prioridade: str | None = None,
        status: str | None = None,
    ):
        if data_inicio:
            consulta = consulta.where(Demanda.data_abertura >= datetime.combine(data_inicio, time.min))
        if data_fim:
            consulta = consulta.where(Demanda.data_abertura <= datetime.combine(data_fim, time.max))
        if categoria:
            consulta = consulta.where(Demanda.categoria == categoria)
        if prioridade:
            consulta = consulta.where(Demanda.prioridade == prioridade)
        if status:
            consulta = consulta.where(Demanda.status == status)
        return consulta

    @staticmethod
    def criar(
        db: Session,
        gabinete_id: int,
        eleitor_id: str | None,
        titulo: str,
        descricao: str | None,
        categoria_id: str | None,
        subcategoria_id: str | None,
        status: str | None,
        prioridade: str | None,
        responsavel: str | None = None,
        prazo: date | None = None,
        observacoes_internas: str | None = None,
        secretaria: str | None = None,
        ref_historico: str | None = None,
        data_abertura: datetime | None = None,
        data_solicitacao: date | None = None,
        fechar_automaticamente: bool = True,
        eleitor_obrigatorio: bool = True,
        commit: bool = True,
        origem: str = "INTERNA",
        usuario_id: int | None = None,
        registrar_historico: bool = True,
    ) -> Demanda:
        # secretaria/ref_historico/data_abertura/fechar_automaticamente/
        # eleitor_obrigatorio existem para a importação histórica
        # (atendimento.csv): permitem gravar a data original do atendimento,
        # desligar o fechamento automático e aceitar demanda sem eleitor
        # vinculado (o CSV real do Meu Mandato permite "Ref. eleitor" vazio
        # ou não encontrado), sem alterar o comportamento do formulário
        # normal (que não passa esses argumentos e continua exigindo
        # eleitor). O status já chega traduzido para o vocabulário oficial
        # (STATUS_OPCOES) antes de chegar aqui — não existe mais um
        # vocabulário paralelo gravado no banco.
        dados = DemandaService._validar_dados(
            db,
            gabinete_id,
            eleitor_id,
            titulo,
            descricao,
            categoria_id,
            subcategoria_id,
            status,
            prioridade,
            eleitor_obrigatorio=eleitor_obrigatorio,
        )
        demanda = Demanda(
            gabinete_id=gabinete_id,
            eleitor_id=dados["eleitor_id"],
            titulo=dados["titulo"],
            descricao=dados["descricao"],
            categoria=dados["categoria_nome"],
            categoria_id=dados["categoria_id"],
            subcategoria_id=dados["subcategoria_id"],
            status=dados["status"],
            prioridade=dados["prioridade"],
            responsavel=(responsavel or "").strip() or None,
            prazo=prazo,
            observacoes_internas=(observacoes_internas or "").strip() or None,
            secretaria=(secretaria or "").strip() or None,
            ref_historico=ref_historico,
            data_abertura=data_abertura or datetime.now(),
            # Sem data_solicitacao explícita: usa a data do próprio
            # data_abertura quando ele foi informado (importação
            # histórica — preserva a data real do atendimento antigo, em
            # vez da data de hoje), senão a data de hoje (cadastro normal,
            # incluindo o atendimento público — coerente com a data do
            # próprio protocolo).
            data_solicitacao=data_solicitacao
            or (data_abertura.date() if data_abertura else date.today()),
            data_fechamento=(
                datetime.now() if fechar_automaticamente and dados["status"] == "Concluído" else None
            ),
            origem=origem,
        )
        db.add(demanda)
        # flush (não só no commit=False): precisa de demanda.id já
        # preenchido para o primeiro HistoricoDemanda logo abaixo — tanto
        # para o caminho commit=False (importador de CSV, que também usa
        # este flush para sincronizar_retorno_demanda) quanto para o
        # caminho commit=True, onde antes esse flush só aconteceria
        # implicitamente dentro do db.commit() final.
        db.flush()

        if registrar_historico:
            # Only a demanda pública leva essa observação — a criação
            # interna não precisa de um texto especial (o próprio
            # usuario_id já identifica quem criou).
            observacao = (
                "Demanda registrada pelo atendimento público."
                if origem == "PUBLICA"
                else None
            )
            HistoricoDemandaService.registrar(
                db,
                gabinete_id=gabinete_id,
                demanda_id=demanda.id,
                status_novo=dados["status"],
                status_anterior=None,
                usuario_id=usuario_id,
                observacao=observacao,
            )

        if not commit:
            # commit=False é usado só pelo importador de CSV (commit em
            # lote, não por linha; registrar_historico=False nesse
            # caminho — ver DemandaCsvService) e por
            # AtendimentoPublicoService (que ainda precisa subir fotos
            # antes do commit final).
            AgendaService.sincronizar_retorno_demanda(db, demanda)
            return demanda
        db.commit()
        db.refresh(demanda)
        AgendaService.sincronizar_retorno_demanda(db, demanda)
        return demanda

    @staticmethod
    def atualizar(
        db: Session,
        demanda: Demanda,
        eleitor_id: str | None,
        titulo: str,
        descricao: str | None,
        categoria_id: str | None,
        subcategoria_id: str | None,
        status: str | None,
        prioridade: str | None,
        responsavel: str | None = None,
        prazo: date | None = None,
        observacoes_internas: str | None = None,
        data_solicitacao: date | None = None,
        usuario_id: int | None = None,
    ) -> Demanda:
        dados = DemandaService._validar_dados(
            db,
            demanda.gabinete_id,
            eleitor_id,
            titulo,
            descricao,
            categoria_id,
            subcategoria_id,
            status,
            prioridade,
        )

        if demanda.status == "Concluído" and dados["status"] == "Protocolado":
            raise ValueError("Não é possível reabrir uma demanda concluída.")

        # Capturado antes de qualquer mutação em demanda.status logo
        # abaixo — é o valor real "antes desta edição", para o histórico.
        status_anterior = demanda.status

        if dados["status"] == "Concluído" and demanda.status != "Concluído":
            demanda.data_fechamento = datetime.now()
        elif dados["status"] != "Concluído" and demanda.status == "Concluído":
            demanda.data_fechamento = None

        demanda.eleitor_id = dados["eleitor_id"]
        demanda.titulo = dados["titulo"]
        demanda.descricao = dados["descricao"]
        demanda.categoria = dados["categoria_nome"]
        demanda.categoria_id = dados["categoria_id"]
        demanda.subcategoria_id = dados["subcategoria_id"]
        demanda.status = dados["status"]
        demanda.prioridade = dados["prioridade"]
        demanda.responsavel = (responsavel or "").strip() or None
        demanda.prazo = prazo
        demanda.observacoes_internas = (observacoes_internas or "").strip() or None
        # Mantém a data já gravada quando o formulário não envia uma nova
        # (nunca None — a coluna é NOT NULL) — só troca quando o usuário
        # de fato ajusta o campo na edição.
        if data_solicitacao is not None:
            demanda.data_solicitacao = data_solicitacao

        # Só grava histórico quando o status realmente mudou — trocar
        # título/descrição/prioridade/etc. sem trocar status não gera
        # evento. Mesma transação da atualização da própria demanda:
        # HistoricoDemandaService.registrar só adiciona à sessão, o
        # commit abaixo grava as duas coisas juntas (e um rollback
        # desfaz as duas juntas).
        if status_anterior != demanda.status:
            HistoricoDemandaService.registrar(
                db,
                gabinete_id=demanda.gabinete_id,
                demanda_id=demanda.id,
                status_novo=demanda.status,
                status_anterior=status_anterior,
                usuario_id=usuario_id,
            )

        db.commit()
        db.refresh(demanda)
        AgendaService.sincronizar_retorno_demanda(db, demanda)
        return demanda

    @staticmethod
    def excluir(db: Session, demanda: Demanda) -> None:
        """Exclusão definitiva de uma Demanda — só o fluxo interno
        autenticado chama isto (nunca o módulo público /cidadao, que não
        tem nenhuma rota de exclusão). R2 e PostgreSQL não formam uma
        transação distribuída: por isso, se a demanda tem algum anexo
        com arquivo ainda no storage, TODOS os objetos são removidos do
        R2 primeiro — nenhum registro do banco é tocado antes disso. Só
        depois de confirmado que o storage está limpo é que
        DemandaAnexo, HistoricoDemanda e a própria Demanda são apagados,
        em UM único commit (caminho normal: nunca "demanda excluída sem
        se saber se o anexo foi" nem "anexo apagado do R2 sem o registro
        correspondente desaparecer").

        Se algum objeto falhar ao ser removido do R2: nada é apagado do
        banco (nem a Demanda, nem nenhum DemandaAnexo, nem o
        HistoricoDemanda) — levanta FalhaExclusaoAnexoError, e o
        chamador decide o que mostrar.

        Janela de corrida entre R2 e o commit (achado numa revisão
        posterior): marcar arquivo_disponivel=False só DEPOIS que
        storage.excluir() confirma sucesso deixava uma janela aberta —
        entre o objeto já ter sumido fisicamente do R2 e o commit que
        registra isso, uma outra requisição (ex.: abrir_anexo) ainda lia
        arquivo_disponivel=True do último commit e conseguia gerar uma
        URL assinada para um objeto que já não existia mais. Por isso,
        agora arquivo_disponivel é derrubado a False e COMITADO para
        TODOS os anexos pendentes ANTES de qualquer chamada ao R2 —
        fecha a janela por completo, porque nenhuma leitura concorrente
        (sempre um SELECT simples, nunca bloqueado por lock de outra
        transação em READ COMMITTED) volta a enxergar True depois desse
        commit, não importa se o R2 ainda não foi tocado.

        Isso por si só criaria um novo problema (marcar indisponível
        antes de confirmar a remoção de verdade) se o campo usado para
        decidir o que precisa de nova tentativa continuasse sendo
        arquivo_disponivel — por isso quem decide "ainda falta excluir
        do R2" é sempre excluido_em IS NULL (nunca arquivo_disponivel),
        preenchido com a hora só quando storage.excluir() de fato
        confirma sucesso. As três combinações possíveis de
        (arquivo_disponivel, excluido_em) passam a significar:
          - (True,  None)   -> normal, nunca tocado por uma exclusão;
          - (False, None)   -> exclusão em andamento ou que falhou nesse
                                anexo específico: precisa de nova
                                tentativa (idempotente — o DELETE do
                                S3/R2 não quebra nada se repetido, tenha
                                o objeto sido removido antes ou não);
          - (False, <hora>) -> confirmado removido do R2.
        Numa nova tentativa (ou depois de a aplicação cair no meio do
        processo), o filtro por excluido_em IS NULL sempre encontra
        exatamente o que ainda falta processar, sem depender de saber
        se aquele anexo específico já tinha sido marcado indisponível
        numa tentativa anterior."""
        anexos = DemandaAnexoService.listar_todos_por_demanda(db, demanda.id)
        anexos_pendentes = [anexo for anexo in anexos if anexo.excluido_em is None]

        if anexos_pendentes:
            storage = obter_storage_service()
            if storage is None:
                logger.error(
                    "Exclusão de demanda_id=%s (gabinete_id=%s) abortada: existem %d anexo(s) "
                    "pendente(s) e o storage não está configurado neste ambiente.",
                    demanda.id, demanda.gabinete_id, len(anexos_pendentes),
                )
                raise FalhaExclusaoAnexoError(MENSAGEM_FALHA_EXCLUSAO_ANEXO)

            # Derruba e comita ANTES de qualquer chamada ao R2 — ver
            # docstring acima. A partir deste commit, nenhuma leitura
            # concorrente volta a considerar estes anexos disponíveis.
            for anexo in anexos_pendentes:
                anexo.arquivo_disponivel = False
            db.commit()

            houve_falha = False
            for anexo in anexos_pendentes:
                if storage.excluir(anexo.storage_key):
                    anexo.excluido_em = datetime.now()
                else:
                    houve_falha = True
                    logger.error(
                        "Falha ao excluir do R2 o anexo id=%s (demanda_id=%s, gabinete_id=%s) "
                        "durante exclusão de demanda.",
                        anexo.id, demanda.id, demanda.gabinete_id,
                    )

            if houve_falha:
                # Persiste só as marcações de sucesso já aplicadas acima
                # (excluido_em dos que confirmaram saída do R2) — nunca
                # a Demanda, nunca o HistoricoDemanda, nunca o
                # DemandaAnexo que falhou. A demanda continua existindo
                # e disponível para uma nova tentativa de exclusão.
                db.commit()
                raise FalhaExclusaoAnexoError(MENSAGEM_FALHA_EXCLUSAO_ANEXO)

        AgendaService.excluir_compromisso_da_demanda(db, demanda.gabinete_id, demanda.id)
        db.execute(delete(DemandaAnexo).where(DemandaAnexo.demanda_id == demanda.id))
        db.execute(delete(HistoricoDemanda).where(HistoricoDemanda.demanda_id == demanda.id))
        # Uma demanda de origem pública sempre tem uma SubmissaoCidadao
        # apontando para ela (trava de idempotência do envio — ver
        # Prompt 2.1); sem isto, a FK submissoes_cidadao_demanda_id_fkey
        # impede o DELETE de demandas abaixo. Depois que a demanda em si
        # vai ser apagada, a linha de idempotência não tem mais nenhuma
        # finalidade (o token já cumpriu seu papel no momento do envio).
        db.execute(delete(SubmissaoCidadao).where(SubmissaoCidadao.demanda_id == demanda.id))
        db.delete(demanda)
        db.commit()

    @staticmethod
    def _validar_dados(
        db: Session,
        gabinete_id: int,
        eleitor_id: str | None,
        titulo: str,
        descricao: str | None,
        categoria_id: str | None,
        subcategoria_id: str | None,
        status: str | None,
        prioridade: str | None,
        eleitor_obrigatorio: bool = True,
    ) -> dict[str, Any]:
        try:
            eleitor_id_convertido = int(eleitor_id) if eleitor_id else None
        except (TypeError, ValueError):
            eleitor_id_convertido = None

        if eleitor_id_convertido is not None:
            # Nunca confiar num eleitor_id só porque é um inteiro válido —
            # tem que existir E pertencer ao mesmo gabinete da demanda,
            # senão um ID adivinhado vincularia dado de outro gabinete.
            eleitor_obj = db.get(Eleitor, eleitor_id_convertido)
            if eleitor_obj is None or eleitor_obj.gabinete_id != gabinete_id:
                raise ValueError("Eleitor não encontrado.")
        if eleitor_id_convertido is None and eleitor_obrigatorio:
            raise ValueError("Eleitor obrigatório.")

        titulo_normalizado = (titulo or "").strip()
        if len(titulo_normalizado) < TITULO_MINIMO_CARACTERES:
            raise ValueError("Título inválido.")

        descricao_normalizada = (descricao or "").strip()
        if not descricao_normalizada:
            raise ValueError("Descrição obrigatória.")

        try:
            categoria_id_convertido = int(categoria_id) if categoria_id else None
        except (TypeError, ValueError):
            categoria_id_convertido = None

        categoria_obj = (
            db.get(Categoria, categoria_id_convertido) if categoria_id_convertido else None
        )
        if categoria_obj is None or categoria_obj.gabinete_id != gabinete_id:
            raise ValueError("Categoria obrigatória.")

        subcategoria_id_convertido = None
        if subcategoria_id and subcategoria_id.strip():
            try:
                subcategoria_id_convertido = int(subcategoria_id)
            except (TypeError, ValueError):
                raise ValueError("Subcategoria inválida.")
            subcategoria_obj = db.get(Subcategoria, subcategoria_id_convertido)
            if subcategoria_obj is None or subcategoria_obj.categoria_id != categoria_obj.id:
                raise ValueError("Subcategoria não pertence à categoria selecionada.")

        if status not in STATUS_OPCOES:
            raise ValueError("Status obrigatório.")

        if prioridade not in PRIORIDADE_OPCOES:
            raise ValueError("Prioridade obrigatória.")

        return {
            "eleitor_id": eleitor_id_convertido,
            "titulo": titulo_normalizado,
            "descricao": descricao_normalizada,
            "categoria_id": categoria_obj.id,
            "categoria_nome": categoria_obj.nome,
            "subcategoria_id": subcategoria_id_convertido,
            "status": status,
            "prioridade": prioridade,
        }
