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
    def _criar_usuario_com_senha(db: Session, nome: str, email: str, senha: str) -> Usuario:
        """Validação de nome/e-mail/senha + hash + persistência de Usuario,
        compartilhada por criar_usuario_e_membro (tela do ADMIN) e
        criar_usuario_e_membro_superadmin (tela do SUPERADMIN) — só o
        conjunto de perfis permitidos para o MembroGabinete difere entre os
        dois, então essa parte fica igual para os dois. flush() (não
        commit()): quem chama decide quando fechar a transação, depois de
        também criar o MembroGabinete — nunca fica um Usuario sem vínculo
        se o passo seguinte falhar."""
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome inválido.")

        email_normalizado = (email or "").strip().lower()
        if "@" not in email_normalizado:
            raise ValueError("E-mail inválido.")

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
        return usuario

    @staticmethod
    def criar_usuario_e_membro(
        db: Session, gabinete_id: int, nome: str, email: str, senha: str, perfil: str
    ) -> MembroGabinete:
        if perfil not in PERFIS_ATRIBUIVEIS_PELA_UI:
            raise ValueError("Perfil inválido.")

        usuario = UsuarioService._criar_usuario_com_senha(db, nome, email, senha)

        membro = MembroGabinete(usuario_id=usuario.id, gabinete_id=gabinete_id, perfil=perfil, ativo=True)
        db.add(membro)
        db.commit()
        db.refresh(membro)
        return membro

    @staticmethod
    def criar_usuario_e_membro_superadmin(
        db: Session, gabinete_id: int, nome: str, email: str, senha: str, perfil: str
    ) -> MembroGabinete:
        """Só para rotas /superadmin (Depends(exigir_superadmin)) — mesma
        validação/hash de criar_usuario_e_membro, mas sem a restrição de
        PERFIS_ATRIBUIVEIS_PELA_UI: o SUPERADMIN pode atribuir ADMIN
        diretamente (um gabinete pode ter vários ADMINs simultâneos — não
        existe "ADMIN exclusivo"). "SUPERADMIN" nunca é um valor aceito
        aqui: não é um perfil de MembroGabinete, é o campo separado
        Usuario.super_admin (promovido só pelo mecanismo de bootstrap
        próprio), e este formulário nunca oferece essa opção."""
        if perfil not in PERFIS_OPCOES:
            raise ValueError("Perfil inválido.")

        usuario = UsuarioService._criar_usuario_com_senha(db, nome, email, senha)

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
    def atualizar_membro_superadmin(
        db: Session, gabinete_id: int, membro: MembroGabinete, nome: str, email: str, perfil: str, ativo: bool
    ) -> MembroGabinete:
        """Só para rotas /superadmin — diferente de atualizar_membro()
        (tela do ADMIN comum, que só edita perfil/ativo e nunca promove a
        ADMIN): aqui o SUPERADMIN também pode editar nome/e-mail do
        Usuario e promover/rebaixar livremente entre ADMIN/VEREADOR/
        ASSESSOR. Mantém a mesma trava de não deixar o gabinete sem
        nenhum ADMIN ativo — mesmo o SUPERADMIN precisa promover outra
        pessoa antes de rebaixar/desativar o último."""
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome inválido.")

        email_normalizado = (email or "").strip().lower()
        if "@" not in email_normalizado:
            raise ValueError("E-mail inválido.")

        outro_usuario_com_email = db.scalar(
            select(Usuario).where(Usuario.email == email_normalizado, Usuario.id != membro.usuario_id)
        )
        if outro_usuario_com_email is not None:
            raise ValueError("Já existe outro usuário com este e-mail.")

        if perfil not in PERFIS_OPCOES:
            raise ValueError("Perfil inválido.")

        vai_perder_admin_ativo = membro.perfil == "ADMIN" and (perfil != "ADMIN" or not ativo)
        if vai_perder_admin_ativo:
            outros = UsuarioService.contar_admins_ativos(db, gabinete_id, ignorar_membro_id=membro.id)
            if outros == 0:
                raise ValueError("Não é possível remover o último administrador ativo do gabinete.")

        membro.usuario.nome = nome_normalizado
        membro.usuario.email = email_normalizado
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
