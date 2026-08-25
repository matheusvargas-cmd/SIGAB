from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.security import gerar_hash_senha
from app.models.membro_gabinete import PERFIS_OPCOES, MembroGabinete
from app.models.usuario import Usuario

NOME_MINIMO_CARACTERES = 2
SENHA_MINIMO_CARACTERES = 8

# O perfil ADMIN nunca é atribuído pela interface normal — só existe via
# scripts/criar_primeiro_admin.py (bootstrap) ou gestão direta no banco.
# Isso vale tanto para criar um membro quanto para editar um já existente
# (ver _validar_escalada em atualizar_membro): a UI nunca oferece "ADMIN"
# como opção para promover alguém que ainda não é.
PERFIS_ATRIBUIVEIS_PELA_UI = ["VEREADOR", "ASSESSOR"]


class UsuarioService:
    """Administração de usuários/membros de um gabinete — toda consulta e
    escrita aqui é sempre filtrada por gabinete_id, a mesma fronteira de
    isolamento multi-tenant usada por Eleitor/Demanda/Agenda/Categoria (ver
    app/core/contexto.py). Nunca aceitar gabinete_id vindo do cliente."""

    @staticmethod
    def listar_membros(db: Session, gabinete_id: int) -> list[MembroGabinete]:
        consulta = (
            select(MembroGabinete)
            .where(MembroGabinete.gabinete_id == gabinete_id)
            .join(Usuario, MembroGabinete.usuario_id == Usuario.id)
            .options(joinedload(MembroGabinete.usuario))
            .order_by(Usuario.nome)
        )
        return list(db.scalars(consulta).unique().all())

    @staticmethod
    def obter_membro(db: Session, gabinete_id: int, membro_id: int) -> MembroGabinete | None:
        membro = db.get(MembroGabinete, membro_id)
        if membro is None or membro.gabinete_id != gabinete_id:
            return None
        return membro

    @staticmethod
    def contar_admins_ativos(
        db: Session, gabinete_id: int, ignorar_membro_id: int | None = None
    ) -> int:
        consulta = (
            select(func.count())
            .select_from(MembroGabinete)
            .where(
                MembroGabinete.gabinete_id == gabinete_id,
                MembroGabinete.perfil == "ADMIN",
                MembroGabinete.ativo.is_(True),
            )
        )
        if ignorar_membro_id is not None:
            consulta = consulta.where(MembroGabinete.id != ignorar_membro_id)
        return db.scalar(consulta) or 0

    @staticmethod
    def usuario_pertence_a_outros_gabinetes(db: Session, membro: MembroGabinete) -> bool:
        consulta = (
            select(func.count())
            .select_from(MembroGabinete)
            .where(
                MembroGabinete.usuario_id == membro.usuario_id,
                MembroGabinete.gabinete_id != membro.gabinete_id,
            )
        )
        return (db.scalar(consulta) or 0) > 0

    @staticmethod
    def buscar_usuario_por_email(db: Session, email: str) -> Usuario | None:
        email_normalizado = (email or "").strip().lower()
        if not email_normalizado:
            return None
        return db.scalar(select(Usuario).where(Usuario.email == email_normalizado))

    @staticmethod
    def criar_usuario_e_membro(
        db: Session, gabinete_id: int, nome: str, email: str, senha: str, perfil: str
    ) -> MembroGabinete:
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome inválido.")

        email_normalizado = (email or "").strip().lower()
        if "@" not in email_normalizado:
            raise ValueError("E-mail inválido.")

        if perfil not in PERFIS_ATRIBUIVEIS_PELA_UI:
            raise ValueError("Perfil inválido.")

        if len(senha or "") < SENHA_MINIMO_CARACTERES:
            raise ValueError(f"Senha muito curta — mínimo {SENHA_MINIMO_CARACTERES} caracteres.")

        if db.scalar(select(Usuario).where(Usuario.email == email_normalizado)) is not None:
            raise ValueError(
                'Já existe um usuário com este e-mail. Use "Adicionar usuário existente".'
            )

        usuario = Usuario(
            nome=nome_normalizado, email=email_normalizado, senha_hash=gerar_hash_senha(senha), ativo=True
        )
        db.add(usuario)
        db.flush()

        membro = MembroGabinete(usuario_id=usuario.id, gabinete_id=gabinete_id, perfil=perfil, ativo=True)
        db.add(membro)
        db.commit()
        db.refresh(membro)
        return membro

    @staticmethod
    def adicionar_usuario_existente(
        db: Session, gabinete_id: int, email: str, perfil: str
    ) -> MembroGabinete:
        # Sempre re-resolve o usuário pelo e-mail aqui dentro (nunca aceita
        # um usuario_id vindo do formulário) — a etapa de confirmação da
        # tela só carrega o e-mail de volta, exatamente para que este
        # método seja a única fonte de verdade sobre qual conta está sendo
        # vinculada, sem depender de um ID que o cliente poderia adulterar.
        if perfil not in PERFIS_ATRIBUIVEIS_PELA_UI:
            raise ValueError("Perfil inválido.")

        usuario = UsuarioService.buscar_usuario_por_email(db, email)
        if usuario is None:
            raise ValueError("Usuário não encontrado.")

        existente = db.scalar(
            select(MembroGabinete).where(
                MembroGabinete.usuario_id == usuario.id, MembroGabinete.gabinete_id == gabinete_id
            )
        )
        if existente is not None:
            raise ValueError("Este usuário já pertence a este gabinete.")

        membro = MembroGabinete(usuario_id=usuario.id, gabinete_id=gabinete_id, perfil=perfil, ativo=True)
        db.add(membro)
        db.commit()
        db.refresh(membro)
        return membro

    @staticmethod
    def atualizar_membro(
        db: Session, gabinete_id: int, membro: MembroGabinete, perfil: str, ativo: bool
    ) -> MembroGabinete:
        if perfil not in PERFIS_OPCOES:
            raise ValueError("Perfil inválido.")
        if perfil == "ADMIN" and membro.perfil != "ADMIN":
            # Escalada de privilégio: só quem já é ADMIN continua ADMIN por
            # aqui — ninguém é promovido a ADMIN pela interface.
            raise ValueError("O perfil ADMIN não pode ser concedido pela interface.")

        vai_perder_admin_ativo = membro.perfil == "ADMIN" and (perfil != "ADMIN" or not ativo)
        if vai_perder_admin_ativo:
            outros = UsuarioService.contar_admins_ativos(db, gabinete_id, ignorar_membro_id=membro.id)
            if outros == 0:
                raise ValueError("Não é possível remover o último administrador ativo do gabinete.")

        membro.perfil = perfil
        membro.ativo = ativo
        db.commit()
        db.refresh(membro)
        return membro

    @staticmethod
    def alternar_ativo(db: Session, gabinete_id: int, membro: MembroGabinete) -> MembroGabinete:
        novo_ativo = not membro.ativo
        if membro.perfil == "ADMIN" and not novo_ativo:
            outros = UsuarioService.contar_admins_ativos(db, gabinete_id, ignorar_membro_id=membro.id)
            if outros == 0:
                raise ValueError("Não é possível remover o último administrador ativo do gabinete.")
        membro.ativo = novo_ativo
        db.commit()
        db.refresh(membro)
        return membro

    @staticmethod
    def definir_senha(db: Session, membro: MembroGabinete, nova_senha: str) -> None:
        if len(nova_senha or "") < SENHA_MINIMO_CARACTERES:
            raise ValueError(f"Senha muito curta — mínimo {SENHA_MINIMO_CARACTERES} caracteres.")
        membro.usuario.senha_hash = gerar_hash_senha(nova_senha)
        db.commit()
