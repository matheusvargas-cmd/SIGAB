from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import gerar_hash_senha
from app.models.agenda import Agenda
from app.models.categoria import Categoria
from app.models.demanda import Demanda
from app.models.eleitor import Eleitor
from app.models.gabinete import Gabinete
from app.models.membro_gabinete import MembroGabinete
from app.models.usuario import Usuario
from app.services.demanda_service import CATEGORIAS

NOME_MINIMO_CARACTERES = 2
SENHA_MINIMO_CARACTERES = 8


class GabineteService:
    """O Gabinete atual já chega resolvido em ContextoSessao.gabinete (ver
    app/core/contexto.py) — não existe um "listar" aqui de propósito: um
    ADMIN só edita o próprio gabinete, nunca escolhe outro pelo ID.

    Os métodos abaixo com sufixo "_superadmin" (e criar_gabinete_com_admin,
    contadores) são a exceção deliberada: só chamados pelas rotas de
    /superadmin (Depends(exigir_superadmin), nunca exigir_perfil), onde
    enxergar/administrar todos os gabinetes é exatamente o propósito. Não
    reaproveitam nem alteram atualizar() acima, que continua exclusivo do
    ADMIN editando o próprio gabinete."""

    @staticmethod
    def atualizar(
        db: Session, gabinete: Gabinete, nome: str, ativo: bool, email_institucional: str = ""
    ) -> Gabinete:
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome do gabinete inválido.")

        if not ativo and gabinete.ativo:
            # Desativar o PRÓPRIO gabinete atualmente selecionado tiraria o
            # acesso de todo mundo (inclusive de quem está fazendo isso)
            # imediatamente, sem nenhuma tela para reverter — só o script
            # de bootstrap/acesso direto ao banco resolveria depois. Mesmo
            # princípio do "não remover o último admin ativo", aplicado ao
            # gabinete em si.
            raise ValueError(
                "Não é possível desativar o gabinete que você está usando agora. "
                "Peça para outro administrador desativá-lo, ou faça isso fora do sistema."
            )

        email_normalizado = (email_institucional or "").strip().lower()
        if email_normalizado and "@" not in email_normalizado:
            raise ValueError("E-mail institucional inválido.")

        gabinete.nome = nome_normalizado
        gabinete.ativo = ativo
        gabinete.email_institucional = email_normalizado or None
        db.commit()
        db.refresh(gabinete)
        return gabinete

    @staticmethod
    def listar_todos(db: Session) -> list[Gabinete]:
        return list(db.scalars(select(Gabinete).order_by(Gabinete.nome)).all())

    @staticmethod
    def obter_por_id(db: Session, gabinete_id: int) -> Gabinete | None:
        return db.get(Gabinete, gabinete_id)

    @staticmethod
    def contadores(db: Session, gabinete_id: int) -> dict:
        """Só contagens agregadas — nunca uma consulta que devolva linha de
        eleitor/demanda/agenda em si. É o que mantém o painel do SUPERADMIN
        dentro do isolamento multi-tenant: ele vê "quantos", nunca "quais"."""
        return {
            "usuarios": db.scalar(
                select(func.count())
                .select_from(MembroGabinete)
                .where(MembroGabinete.gabinete_id == gabinete_id, MembroGabinete.ativo.is_(True))
            )
            or 0,
            "eleitores": db.scalar(
                select(func.count()).select_from(Eleitor).where(Eleitor.gabinete_id == gabinete_id)
            )
            or 0,
            "demandas": db.scalar(
                select(func.count()).select_from(Demanda).where(Demanda.gabinete_id == gabinete_id)
            )
            or 0,
            "agenda": db.scalar(
                select(func.count()).select_from(Agenda).where(Agenda.gabinete_id == gabinete_id)
            )
            or 0,
        }

    @staticmethod
    def criar_gabinete_com_admin(
        db: Session,
        nome_gabinete: str,
        responsavel: str | None,
        nome_admin: str,
        email_admin: str,
        senha_admin: str,
    ) -> Gabinete:
        """Cria gabinete + usuário ADMIN + vínculo + as 13 categorias
        oficiais numa única transação — se qualquer etapa falhar, tudo é
        desfeito (nenhum commit acontece até o fim), nunca sobra um
        gabinete pela metade. Não reaproveita
        MigrationService.semear_categorias_para_gabinete() de propósito:
        aquele método abre sua própria Session (outra transação, outro
        commit) — incompatível com a garantia de tudo-ou-nada exigida
        aqui. Espelha exatamente a mesma lista de categorias
        (demanda_service.CATEGORIAS), só que dentro da mesma transação do
        gabinete/admin sendo criados."""
        nome_gabinete_normalizado = (nome_gabinete or "").strip()
        if len(nome_gabinete_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome do gabinete inválido.")

        responsavel_normalizado = (responsavel or "").strip() or None

        nome_admin_normalizado = (nome_admin or "").strip()
        if len(nome_admin_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome do administrador inválido.")

        email_normalizado = (email_admin or "").strip().lower()
        if "@" not in email_normalizado:
            raise ValueError("E-mail do administrador inválido.")

        if len(senha_admin or "") < SENHA_MINIMO_CARACTERES:
            raise ValueError(f"Senha muito curta — mínimo {SENHA_MINIMO_CARACTERES} caracteres.")

        if db.scalar(select(Usuario).where(Usuario.email == email_normalizado)) is not None:
            raise ValueError("Já existe um usuário com este e-mail.")

        try:
            gabinete = Gabinete(
                nome=nome_gabinete_normalizado, responsavel=responsavel_normalizado, ativo=True
            )
            db.add(gabinete)
            db.flush()

            usuario = Usuario(
                nome=nome_admin_normalizado,
                email=email_normalizado,
                senha_hash=gerar_hash_senha(senha_admin),
                ativo=True,
            )
            db.add(usuario)
            db.flush()

            membro = MembroGabinete(
                usuario_id=usuario.id, gabinete_id=gabinete.id, perfil="ADMIN", ativo=True
            )
            db.add(membro)

            for nome_categoria in CATEGORIAS:
                db.add(Categoria(gabinete_id=gabinete.id, nome=nome_categoria, ativo=True))

            db.commit()
        except Exception:
            db.rollback()
            raise

        db.refresh(gabinete)
        return gabinete

    @staticmethod
    def atualizar_superadmin(
        db: Session,
        gabinete: Gabinete,
        nome: str,
        responsavel: str | None,
        ativo: bool,
        email_institucional: str = "",
    ) -> Gabinete:
        """Edição pelo SUPERADMIN — sem a trava de "não desativar o
        gabinete que você está usando agora" de atualizar(): o SUPERADMIN
        nunca "está usando" nenhum gabinete (não tem MembroGabinete), então
        essa trava não se aplica e desativar qualquer gabinete daqui é
        sempre permitido."""
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Nome do gabinete inválido.")

        email_normalizado = (email_institucional or "").strip().lower()
        if email_normalizado and "@" not in email_normalizado:
            raise ValueError("E-mail institucional inválido.")

        gabinete.nome = nome_normalizado
        gabinete.responsavel = (responsavel or "").strip() or None
        gabinete.ativo = ativo
        gabinete.email_institucional = email_normalizado or None
        db.commit()
        db.refresh(gabinete)
        return gabinete

    @staticmethod
    def registrar_envio_diario(db: Session, gabinete_id: int, data: date) -> None:
        """Marca que o e-mail diário deste gabinete, para esta data, já foi
        enviado com sucesso — ver Gabinete.ultimo_email_diario_data. Só deve
        ser chamado DEPOIS do SMTP confirmar o envio (nunca antes), para que
        uma falha no meio do caminho deixe uma nova tentativa possível no
        mesmo dia."""
        gabinete = db.get(Gabinete, gabinete_id)
        if gabinete is None:
            return
        gabinete.ultimo_email_diario_data = data
        db.commit()

    @staticmethod
    def ja_enviou_diario_hoje(db: Session, gabinete_id: int, data: date) -> bool:
        gabinete = db.get(Gabinete, gabinete_id)
        return gabinete is not None and gabinete.ultimo_email_diario_data == data
