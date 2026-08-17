import unicodedata


def normalizar(texto: str | None) -> str | None:
    """Remove acentos e caixa alta/baixa para permitir pesquisa tolerante.

    Usada tanto em Python quanto registrada como função SQL no SQLite
    (ver app/core/database.py), garantindo que o termo buscado e o valor
    da coluna sejam comparados da mesma forma.
    """
    if texto is None:
        return None
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.lower()
