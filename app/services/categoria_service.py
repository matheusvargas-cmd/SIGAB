from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.busca import normalizar
from app.models.categoria import Categoria

NOME_MINIMO_CARACTERES = 2


class CategoriaService:
    """Toda consulta/escrita aqui é sempre filtrada por gabinete_id — ver
    app/core/contexto.py. Nunca montar uma query em Categoria fora daqui."""

    @staticmethod
    def listar(db: Session, gabinete_id: int) -> list[Categoria]:
        consulta = select(Categoria).where(Categoria.gabinete_id == gabinete_id).order_by(Categoria.nome)
        return list(db.scalars(consulta).all())

    @staticmethod
    def listar_ativas(db: Session, gabinete_id: int) -> list[Categoria]:
        consulta = (
            select(Categoria)
            .where(Categoria.gabinete_id == gabinete_id, Categoria.ativo.is_(True))
            .order_by(Categoria.nome)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def listar_nomes_para_filtro(
        db: Session, gabinete_id: int, selecionado: str | None = None
    ) -> list[str]:
        """Nomes de categoria para dropdowns de filtro de relatórios: as
        categorias ativas, mais a categoria atualmente selecionada mesmo
        que esteja inativa — para continuar permitindo filtrar/visualizar
        dados históricos já vinculados a ela (mesmo padrão do formulário
        de Demanda)."""
        nomes = [categoria.nome for categoria in CategoriaService.listar_ativas(db, gabinete_id)]
        if selecionado and selecionado not in nomes:
            if CategoriaService.obter_por_nome(db, gabinete_id, selecionado) is not None:
                nomes.append(selecionado)
                nomes.sort()
        return nomes

    @staticmethod
    def obter_por_id(db: Session, gabinete_id: int, categoria_id: int) -> Categoria | None:
        categoria = db.get(Categoria, categoria_id)
        if categoria is None or categoria.gabinete_id != gabinete_id:
            return None
        return categoria

    @staticmethod
    def obter_por_nome(db: Session, gabinete_id: int, nome: str) -> Categoria | None:
        alvo = normalizar(nome)
        consulta = select(Categoria).where(Categoria.gabinete_id == gabinete_id)
        for categoria in db.scalars(consulta).all():
            if normalizar(categoria.nome) == alvo:
                return categoria
        return None

    @staticmethod
    def criar(db: Session, gabinete_id: int, nome: str) -> Categoria:
        nome_normalizado = CategoriaService._validar_nome(db, gabinete_id, nome)
        categoria = Categoria(gabinete_id=gabinete_id, nome=nome_normalizado, ativo=True)
        db.add(categoria)
        db.commit()
        db.refresh(categoria)
        return categoria

    @staticmethod
    def atualizar(db: Session, categoria: Categoria, nome: str) -> Categoria:
        nome_normalizado = CategoriaService._validar_nome(
            db, categoria.gabinete_id, nome, ignorar_id=categoria.id
        )
        categoria.nome = nome_normalizado
        db.commit()
        db.refresh(categoria)
        return categoria

    @staticmethod
    def alternar_ativo(db: Session, categoria: Categoria) -> Categoria:
        categoria.ativo = not categoria.ativo
        db.commit()
        db.refresh(categoria)
        return categoria

    @staticmethod
    def _validar_nome(
        db: Session, gabinete_id: int, nome: str, ignorar_id: int | None = None
    ) -> str:
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome da categoria inválido.")

        termo = normalizar(nome_normalizado)
        consulta = select(Categoria).where(Categoria.gabinete_id == gabinete_id)
        if ignorar_id is not None:
            consulta = consulta.where(Categoria.id != ignorar_id)
        for candidata in db.scalars(consulta):
            if normalizar(candidata.nome) == termo:
                raise ValueError("Já existe uma categoria com este nome.")
        return nome_normalizado
