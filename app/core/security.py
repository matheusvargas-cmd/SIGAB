from passlib.context import CryptContext

# Argon2id — recomendação atual da OWASP para hash de senha, mais
# resistente a hardware dedicado (GPU/ASIC) que bcrypt e sem a limitação de
# 72 bytes do bcrypt. `deprecated="auto"` permite trocar de esquema no
# futuro sem quebrar hashes já gravados (passlib re-hasheia sozinho no
# próximo login bem-sucedido, se o esquema padrão mudar).
_contexto_senha = CryptContext(schemes=["argon2"], deprecated="auto")


def gerar_hash_senha(senha: str) -> str:
    return _contexto_senha.hash(senha)


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    try:
        return _contexto_senha.verify(senha, hash_armazenado)
    except ValueError:
        # hash malformado/vazio — nunca autentica, nunca derruba a request.
        return False
