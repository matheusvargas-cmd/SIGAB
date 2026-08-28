"""Codificação do valor da mensagem flash guardada em cookie.

Cookies HTTP só aceitam valores codificáveis em latin-1 (é a própria
Starlette que impõe isso em Response.set_cookie, seguindo RFC 6265) — um
caractere fora do latin-1 (ex.: o travessão "—", aspas tipográficas,
emoji) faz o set_cookie() estourar UnicodeEncodeError e a página inteira
vira HTTP 500. Acentos comuns do português (á, é, ç, ã...) já estão
dentro do latin-1 e nunca deram esse erro; o problema é só a pontuação
"esperta"/tipográfica que pode aparecer em mensagens vindas de qualquer
serviço (ex.: DailyEmailService).

quote()/unquote() (urllib.parse, biblioteca padrão) resolvem isso sem
trocar nenhum caractere da mensagem exibida: o cookie guarda a versão
percent-encoded (100% ASCII, portanto sempre latin-1 seguro e sempre um
cookie-value válido por RFC 6265 — nem vírgula/ponto-e-vírgula/aspas
sobra sem escapar), e decodificar_flash() devolve o texto original
exatamente como foi passado para codificar_flash()."""

from urllib.parse import quote, unquote


def codificar_flash(texto: str) -> str:
    return quote(texto, safe="")


def decodificar_flash(valor: str | None) -> str | None:
    if valor is None:
        return None
    return unquote(valor)
