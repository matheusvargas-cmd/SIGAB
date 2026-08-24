from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.busca import normalizar
from app.models.categoria import Categoria
from app.models.subcategoria import Subcategoria

NOME_MINIMO_CARACTERES = 2


class SubcategoriaService:
    """Subcategoria não tem gabinete_id próprio — herda o isolamento por
    tenant através da Categoria pai (ver app/models/subcategoria.py e a
    decisão de Fase 1). Por isso todo método aqui recebe gabinete_id e
    primeiro confirma que a categoria_id informada pertence a esse
    gabinete antes de consultar/gravar qualquer Subcategoria — do
    contrário seria possível acessar subcategorias de outro gabinete
    apenas conhecendo o categoria_id."""

    @staticmethod
    def _categoria_do_gabinete(db: Session, gabinete_id: int, categoria_id: int) -> Categoria | None:
        categoria = db.get(Categoria, categoria_id)
        if categoria is None or categoria.gabinete_id != gabinete_id:
            return None
        return categoria

    @staticmethod
    def listar_por_categoria(db: Session, gabinete_id: int, categoria_id: int) -> list[Subcategoria]:
        if SubcategoriaService._categoria_do_gabinete(db, gabinete_id, categoria_id) is None:
            return []
        consulta = (
            select(Subcategoria)
            .where(Subcategoria.categoria_id == categoria_id)
            .order_by(Subcategoria.nome)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def obter_por_nome(
        db: Session, gabinete_id: int, categoria_id: int, nome: str
    ) -> Subcategoria | None:
        if SubcategoriaService._categoria_do_gabinete(db, gabinete_id, categoria_id) is None:
            return None
        alvo = normalizar(nome)
        consulta = select(Subcategoria).where(Subcategoria.categoria_id == categoria_id)
        for subcategoria in db.scalars(consulta).all():
            if normalizar(subcategoria.nome) == alvo:
                return subcategoria
        return None

    @staticmethod
    def listar_ativas(db: Session, gabinete_id: int) -> list[Subcategoria]:
        consulta = (
            select(Subcategoria)
            .join(Categoria, Categoria.id == Subcategoria.categoria_id)
            .where(Categoria.gabinete_id == gabinete_id, Subcategoria.ativo.is_(True))
            .order_by(Subcategoria.categoria_id, Subcategoria.nome)
        )
        return list(db.scalars(consulta).all())

    @staticmethod
    def obter_por_id(db: Session, gabinete_id: int, subcategoria_id: int) -> Subcategoria | None:
        subcategoria = db.get(Subcategoria, subcategoria_id)
        if subcategoria is None:
            return None
        if SubcategoriaService._categoria_do_gabinete(db, gabinete_id, subcategoria.categoria_id) is None:
            return None
        return subcategoria

    @staticmethod
    def criar(db: Session, gabinete_id: int, categoria_id: int, nome: str) -> Subcategoria:
        if SubcategoriaService._categoria_do_gabinete(db, gabinete_id, categoria_id) is None:
            raise ValueError("Categoria inválida.")
        nome_normalizado = SubcategoriaService._validar_nome(db, categoria_id, nome)
        subcategoria = Subcategoria(categoria_id=categoria_id, nome=nome_normalizado, ativo=True)
        db.add(subcategoria)
        db.commit()
        db.refresh(subcategoria)
        return subcategoria

    @staticmethod
    def atualizar(db: Session, subcategoria: Subcategoria, nome: str) -> Subcategoria:
        nome_normalizado = SubcategoriaService._validar_nome(
            db, subcategoria.categoria_id, nome, ignorar_id=subcategoria.id
        )
        subcategoria.nome = nome_normalizado
        db.commit()
        db.refresh(subcategoria)
        return subcategoria

    @staticmethod
    def alternar_ativo(db: Session, subcategoria: Subcategoria) -> Subcategoria:
        subcategoria.ativo = not subcategoria.ativo
        db.commit()
        db.refresh(subcategoria)
        return subcategoria

    @staticmethod
    def _validar_nome(
        db: Session, categoria_id: int, nome: str, ignorar_id: int | None = None
    ) -> str:
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome da subcategoria inválido.")

        termo = normalizar(nome_normalizado)
        consulta = select(Subcategoria).where(Subcategoria.categoria_id == categoria_id)
        if ignorar_id is not None:
            consulta = consulta.where(Subcategoria.id != ignorar_id)
        for candidata in db.scalars(consulta):
            if normalizar(candidata.nome) == termo:
                raise ValueError("Já existe uma subcategoria com este nome nesta categoria.")
        return nome_normalizado
