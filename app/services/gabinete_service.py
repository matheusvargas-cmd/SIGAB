from sqlalchemy.orm import Session

from app.models.gabinete import Gabinete

NOME_MINIMO_CARACTERES = 2


class GabineteService:
    """O Gabinete atual já chega resolvido em ContextoSessao.gabinete (ver
    app/core/contexto.py) — não existe um "listar" aqui de propósito: um
    ADMIN só edita o próprio gabinete, nunca escolhe outro pelo ID."""

    @staticmethod
    def atualizar(db: Session, gabinete: Gabinete, nome: str, ativo: bool) -> Gabinete:
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

        gabinete.nome = nome_normalizado
        gabinete.ativo = ativo
        db.commit()
        db.refresh(gabinete)
        return gabinete
