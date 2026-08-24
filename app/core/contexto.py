"""Ponto único de leitura da sessão autenticada e do gabinete atual.

Nenhum controller deve ler request.session diretamente nem montar sua
própria consulta de MembroGabinete — sempre passar por
obter_contexto_atual() (ou exigir_perfil(...) quando a rota exigir um
perfil específico). Isso garante que a checagem "o usuário realmente
pertence a este gabinete, e o vínculo está ativo" acontece sempre, em um
lugar só, a cada requisição — nunca confiando cegamente em gabinete_id
guardado no cookie de sessão.
"""

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.gabinete import Gabinete
from app.models.membro_gabinete import MembroGabinete
from app.models.usuario import Usuario


class NaoAutenticado(Exception):
    """Sem usuário autenticado na sessão — redireciona para /login."""


class GabineteNaoSelecionado(Exception):
    """Autenticado, mas sem gabinete atual válido — redireciona para
    /selecionar-gabinete."""


class SemPermissao(Exception):
    """Autenticado, com gabinete, mas o perfil não permite esta ação."""


@dataclass(frozen=True)
class ContextoSessao:
    usuario: Usuario
    gabinete: Gabinete
    membro: MembroGabinete

    @property
    def perfil(self) -> str:
        return self.membro.perfil

    @property
    def gabinete_id(self) -> int:
        return self.gabinete.id


def obter_usuario_atual(request: Request, db: Session = Depends(get_db)) -> Usuario:
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        raise NaoAutenticado()

    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.ativo:
        request.session.clear()
        raise NaoAutenticado()
    return usuario


def obter_contexto_atual(
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(obter_usuario_atual),
) -> ContextoSessao:
    gabinete_id = request.session.get("gabinete_id")
    if not gabinete_id:
        raise GabineteNaoSelecionado()

    # Revalida a cada requisição — nunca assume que o vínculo continua
    # válido só porque estava na sessão. Cobre: usuário removido do
    # gabinete, vínculo desativado, gabinete desativado, ou uma sessão
    # antiga apontando para um gabinete_id que nunca pertenceu a ele.
    membro = db.scalar(
        select(MembroGabinete).where(
            MembroGabinete.usuario_id == usuario.id,
            MembroGabinete.gabinete_id == gabinete_id,
            MembroGabinete.ativo.is_(True),
        )
    )
    if membro is None:
        request.session.pop("gabinete_id", None)
        raise GabineteNaoSelecionado()

    gabinete = db.get(Gabinete, gabinete_id)
    if gabinete is None or not gabinete.ativo:
        request.session.pop("gabinete_id", None)
        raise GabineteNaoSelecionado()

    contexto = ContextoSessao(usuario=usuario, gabinete=gabinete, membro=membro)
    # Guardado em request.state (não na sessão) só para a topbar exibir
    # usuário/gabinete atuais sem que cada controller precise repassar isso
    # manualmente no contexto do template — leitura passiva em
    # shared/base.html, nunca uma segunda fonte de verdade sobre permissão.
    request.state.contexto = contexto
    return contexto


def exigir_perfil(*perfis_permitidos: str):
    """Dependency factory: use Depends(exigir_perfil("ADMIN")) numa rota
    para exigir um perfil específico, além de autenticação/gabinete já
    garantidos por obter_contexto_atual."""

    def _checar(contexto: ContextoSessao = Depends(obter_contexto_atual)) -> ContextoSessao:
        if contexto.perfil not in perfis_permitidos:
            raise SemPermissao()
        return contexto

    return _checar
