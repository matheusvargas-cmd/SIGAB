from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.busca import normalizar
from app.models.categoria import Categoria

NOME_MINIMO_CARACTERES = 2


class CategoriaService:
    @staticmethod
    def listar(db: Session) -> list[Categoria]:
        return list(db.scalars(select(Categoria).order_by(Categoria.nome)).all())

    @staticmethod
    def listar_ativas(db: Session) -> list[Categoria]:
        consulta = select(Categoria).where(Categoria.ativo.is_(True)).order_by(Categoria.nome)
        return list(db.scalars(consulta).all())

    @staticmethod
    def obter_por_id(db: Session, categoria_id: int) -> Categoria | None:
        return db.get(Categoria, categoria_id)

    @staticmethod
    def obter_por_nome(db: Session, nome: str) -> Categoria | None:
        alvo = normalizar(nome)
        for categoria in db.scalars(select(Categoria)).all():
            if normalizar(categoria.nome) == alvo:
                return categoria
        return None

    @staticmethod
    def criar(db: Session, nome: str) -> Categoria:
        nome_normalizado = CategoriaService._validar_nome(db, nome)
        categoria = Categoria(nome=nome_normalizado, ativo=True)
        db.add(categoria)
        db.commit()
        db.refresh(categoria)
        return categoria

    @staticmethod
    def atualizar(db: Session, categoria: Categoria, nome: str) -> Categoria:
        nome_normalizado = CategoriaService._validar_nome(db, nome, ignorar_id=categoria.id)
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
    def _validar_nome(db: Session, nome: str, ignorar_id: int | None = None) -> str:
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome da categoria inválido.")

        termo = normalizar(nome_normalizado)
        consulta = select(Categoria)
        if ignorar_id is not None:
            consulta = consulta.where(Categoria.id != ignorar_id)
        for candidata in db.scalars(consulta):
            if normalizar(candidata.nome) == termo:
                raise ValueError("Já existe uma categoria com este nome.")
        return nome_normalizado
