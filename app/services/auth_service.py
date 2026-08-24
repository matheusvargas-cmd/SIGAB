from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import gerar_hash_senha, verificar_senha
from app.models.usuario import Usuario

# Hash fixo (nunca corresponde a nenhuma senha real) usado só para gastar o
# mesmo tempo de CPU de um verificar_senha() de verdade quando o e-mail não
# existe ou o usuário está inativo. Sem isso, a resposta a e-mail
# inexistente/inativo volta bem mais rápido que a de senha errada (que
# executa o hash Argon2id, deliberadamente lento) — uma diferença de tempo
# mensurável que permite enumerar contas mesmo com a mensagem de erro
# genérica. Calculado uma vez no import, não a cada requisição.
_HASH_FICTICIO = gerar_hash_senha("senha-ficticia-somente-para-normalizar-tempo-de-resposta")


class AuthService:
    @staticmethod
    def autenticar(db: Session, email: str, senha: str) -> Usuario | None:
        """Retorna o Usuario só se email existe, está ativo e a senha bate
        com o hash. Qualquer outro caso retorna None — de propósito, sem
        diferenciar "email não existe" de "senha errada" na resposta (nem
        no tempo de resposta — ver _HASH_FICTICIO acima), para não facilitar
        enumeração de contas (ver tela de login)."""
        email_normalizado = (email or "").strip().lower()
        senha = senha or ""
        if not email_normalizado or not senha:
            return None

        usuario = db.scalar(select(Usuario).where(Usuario.email == email_normalizado))

        # Sempre roda verificar_senha(), mesmo quando não há usuário (ou ele
        # está inativo) — contra hash fictício nesse caso — para que o custo
        # de CPU (e portanto o tempo de resposta) seja o mesmo nos dois
        # casos. `senha_valida` só importa quando usuario existe e está ativo.
        hash_para_conferir = usuario.senha_hash if usuario is not None else _HASH_FICTICIO
        senha_valida = verificar_senha(senha, hash_para_conferir)

        if usuario is None or not usuario.ativo or not senha_valida:
            return None
        return usuario
