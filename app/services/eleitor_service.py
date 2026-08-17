import re
from datetime import date
from math import ceil
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.busca import normalizar
from app.models.demanda import Demanda
from app.models.eleitor import Eleitor

POR_PAGINA = 20
NOME_MINIMO_CARACTERES = 3


class EleitorService:
    @staticmethod
    def listar(
        db: Session, pesquisa: str | None = None, pagina: int = 1
    ) -> tuple[list[Eleitor], int, int]:
        consulta = select(Eleitor).order_by(Eleitor.nome)
        consulta_total = select(func.count()).select_from(Eleitor)

        if pesquisa and pesquisa.strip():
            termo = f"%{normalizar(pesquisa.strip())}%"
            filtro = or_(
                func.normalizar(Eleitor.nome).like(termo),
                func.normalizar(Eleitor.telefone).like(termo),
                func.normalizar(Eleitor.whatsapp).like(termo),
                func.normalizar(Eleitor.cidade).like(termo),
                func.normalizar(Eleitor.bairro).like(termo),
                func.normalizar(Eleitor.cpf).like(termo),
                func.normalizar(Eleitor.titulo_eleitor).like(termo),
            )
            consulta = consulta.where(filtro)
            consulta_total = consulta_total.where(filtro)

        total_registros = db.scalar(consulta_total) or 0
        total_paginas = max(1, ceil(total_registros / POR_PAGINA))
        pagina_atual = min(max(1, pagina), total_paginas)

        consulta = consulta.limit(POR_PAGINA).offset((pagina_atual - 1) * POR_PAGINA)
        eleitores = list(db.scalars(consulta).all())
        return eleitores, pagina_atual, total_paginas

    @staticmethod
    def obter_por_id(db: Session, eleitor_id: int) -> Eleitor | None:
        return db.get(Eleitor, eleitor_id)

    @staticmethod
    def obter_por_ref_historico(db: Session, ref_historico: str) -> Eleitor | None:
        return db.scalar(select(Eleitor).where(Eleitor.ref_historico == ref_historico))

    @staticmethod
    def resolver_selecao(
        db: Session,
        selecionar_eleitor_id: int | None,
        eleitor_id_atual: int | None = None,
        trocar: bool = False,
        sem_eleitor: bool = False,
        ja_existe: bool = False,
    ) -> tuple["Eleitor | None", bool]:
        """Resolve a seleção de eleitor nos formulários de Demanda/Agenda
        (busca por nome em vez de lista única). Retorna (eleitor, resolvido).

        ja_existe=True indica um registro já salvo (edição) cujo eleitor
        (mesmo que nenhum) já é uma escolha válida, e não deve forçar a
        busca a cada vez que a tela é aberta.
        """
        if selecionar_eleitor_id is not None:
            eleitor = EleitorService.obter_por_id(db, selecionar_eleitor_id)
            return eleitor, eleitor is not None
        if trocar:
            return None, False
        if sem_eleitor:
            return None, True
        if eleitor_id_atual:
            eleitor = EleitorService.obter_por_id(db, eleitor_id_atual)
            return eleitor, True
        if ja_existe:
            return None, True
        return None, False

    @staticmethod
    def contar(db: Session) -> int:
        return db.scalar(select(func.count()).select_from(Eleitor)) or 0

    @staticmethod
    def listar_recentes(db: Session, limite: int = 5) -> list[Eleitor]:
        consulta = select(Eleitor).order_by(Eleitor.id.desc()).limit(limite)
        return list(db.scalars(consulta).all())

    @staticmethod
    def listar_todos(db: Session) -> list[Eleitor]:
        return list(db.scalars(select(Eleitor).order_by(Eleitor.nome)).all())

    @staticmethod
    def listar_aniversariantes_hoje(db: Session) -> list[Eleitor]:
        hoje = date.today()
        consulta = (
            select(Eleitor)
            .where(Eleitor.nascimento.isnot(None))
            .where(func.strftime("%m-%d", Eleitor.nascimento) == hoje.strftime("%m-%d"))
            .order_by(Eleitor.nome)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def listar_cidades(db: Session) -> list[str]:
        consulta = (
            select(Eleitor.cidade)
            .where(Eleitor.cidade.isnot(None))
            .distinct()
            .order_by(Eleitor.cidade)
        )
        return [cidade for cidade in db.scalars(consulta).all() if cidade]

    @staticmethod
    def relatorio_por_bairro(db: Session, cidade: str | None = None) -> list[dict]:
        consulta = select(Eleitor.bairro, func.count()).group_by(Eleitor.bairro)
        if cidade:
            consulta = consulta.where(Eleitor.cidade == cidade)

        linhas = db.execute(consulta).all()
        resultado = [
            {"rotulo": bairro or "Não informado", "quantidade": quantidade}
            for bairro, quantidade in linhas
        ]
        resultado.sort(key=lambda item: item["quantidade"], reverse=True)
        return resultado

    @staticmethod
    def criar(
        db: Session,
        nome: str,
        telefone: str | None = None,
        whatsapp: str | None = None,
        nascimento: date | None = None,
        endereco: str | None = None,
        bairro: str | None = None,
        cidade: str | None = None,
        observacoes: str | None = None,
        apelido: str | None = None,
        email: str | None = None,
        cpf: str | None = None,
        titulo_eleitor: str | None = None,
        zona_eleitoral: str | None = None,
        ref_historico: str | None = None,
    ) -> Eleitor:
        dados = EleitorService._normalizar_dados(
            nome=nome,
            telefone=telefone,
            whatsapp=whatsapp,
            nascimento=nascimento,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
            observacoes=observacoes,
            apelido=apelido,
            email=email,
            cpf=cpf,
            titulo_eleitor=titulo_eleitor,
            zona_eleitoral=zona_eleitoral,
            ref_historico=ref_historico,
        )
        EleitorService._validar_duplicidade(db, dados["nome"], dados["telefone"])
        eleitor = Eleitor(**dados)
        db.add(eleitor)
        db.commit()
        db.refresh(eleitor)
        return eleitor

    @staticmethod
    def atualizar(
        db: Session,
        eleitor: Eleitor,
        nome: str,
        telefone: str | None = None,
        whatsapp: str | None = None,
        nascimento: date | None = None,
        endereco: str | None = None,
        bairro: str | None = None,
        cidade: str | None = None,
        observacoes: str | None = None,
        apelido: str | None = None,
        email: str | None = None,
        cpf: str | None = None,
        titulo_eleitor: str | None = None,
        zona_eleitoral: str | None = None,
    ) -> Eleitor:
        # ref_historico não faz parte do formulário de edição (é um
        # identificador interno de importação) e por isso não é aceito nem
        # sobrescrito aqui — evita apagar o vínculo com o CSV histórico ao
        # editar um eleitor pela tela normal.
        dados = EleitorService._normalizar_dados(
            nome=nome,
            telefone=telefone,
            whatsapp=whatsapp,
            nascimento=nascimento,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
            observacoes=observacoes,
            apelido=apelido,
            email=email,
            cpf=cpf,
            titulo_eleitor=titulo_eleitor,
            zona_eleitoral=zona_eleitoral,
        )
        EleitorService._validar_duplicidade(
            db, dados["nome"], dados["telefone"], ignorar_id=eleitor.id
        )
        for campo, valor in dados.items():
            setattr(eleitor, campo, valor)
        db.commit()
        db.refresh(eleitor)
        return eleitor

    @staticmethod
    def excluir(db: Session, eleitor: Eleitor) -> None:
        possui_demandas = db.scalar(
            select(exists().where(Demanda.eleitor_id == eleitor.id))
        )
        if possui_demandas:
            raise ValueError("Eleitor possui demandas vinculadas.")
        db.delete(eleitor)
        db.commit()

    @staticmethod
    def _normalizar_dados(**dados: Any) -> dict[str, Any]:
        nome = (dados.get("nome") or "").strip()
        if len(nome) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome inválido.")

        dados["nome"] = nome
        for campo, valor in dados.items():
            if campo != "nome" and isinstance(valor, str):
                dados[campo] = valor.strip() or None
        return dados

    @staticmethod
    def _validar_duplicidade(
        db: Session, nome: str, telefone: str | None, ignorar_id: int | None = None
    ) -> None:
        # Duplicidade só é verificada quando há telefone, pois é a combinação
        # Nome + Telefone que caracteriza o mesmo cadastro (regra da Release 0.2).
        digitos_telefone = re.sub(r"\D", "", telefone or "")
        if not digitos_telefone:
            return

        consulta = select(Eleitor).where(func.lower(Eleitor.nome) == nome.lower())
        if ignorar_id is not None:
            consulta = consulta.where(Eleitor.id != ignorar_id)

        for candidato in db.scalars(consulta):
            if re.sub(r"\D", "", candidato.telefone or "") == digitos_telefone:
                raise ValueError("Cadastro duplicado.")
