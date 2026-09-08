import re
from urllib.parse import quote

DDI_BRASIL = "55"


class WhatsappLinkService:
    """Só gera o link https://wa.me/... com a mensagem pré-preenchida — nunca
    envia nada sozinho (não existe API/token/automação aqui, de propósito:
    ver a decisão de arquitetura desta etapa). O usuário sempre precisa
    clicar em "Enviar" dentro do WhatsApp."""

    @staticmethod
    def normalizar_telefone(telefone_bruto: str | None) -> str | None:
        """Remove máscara (espaços, parênteses, hífen etc.) e adiciona o DDI
        55 quando ausente. Retorna None se não sobrar um número plausível
        (DDD + número, 10 ou 11 dígitos, ou já com o DDI = 12/13 dígitos).

        Alguns cadastros reais têm mais de um telefone concatenado no mesmo
        campo (ex.: "(32) 9992-81207, (32) 9993-56940" — já visto na
        importação real, ver comentário em app/models/eleitor.py). Aqui só o
        PRIMEIRO número da string é considerado — o e-mail nunca tenta
        adivinhar qual dos vários é o WhatsApp certo.
        """
        if not telefone_bruto:
            return None

        primeiro_numero = telefone_bruto.split(",")[0].split(";")[0]
        digitos = re.sub(r"\D", "", primeiro_numero)
        if not digitos:
            return None

        if digitos.startswith(DDI_BRASIL) and len(digitos) in (12, 13):
            return digitos
        if len(digitos) in (10, 11):
            return DDI_BRASIL + digitos
        return None

    @staticmethod
    def gerar_link(telefone_bruto: str | None, mensagem: str) -> str | None:
        """None se o telefone não for válido — o chamador decide o que
        mostrar nesse caso (ex.: só a mensagem, sem botão)."""
        numero = WhatsappLinkService.normalizar_telefone(telefone_bruto)
        if numero is None:
            return None
        return f"https://wa.me/{numero}?text={quote(mensagem)}"

    @staticmethod
    def montar_mensagem_demanda(
        nome_eleitor: str, nome_gabinete: str, demanda_id: int, titulo: str, status: str
    ) -> str:
        """Mensagem pré-preenchida para a tela de visualização de demanda
        (app/modules/demandas/controller.py) — só o texto; o link em si
        continua sendo gerado por gerar_link() acima, sem duplicar
        normalização de telefone nem nenhuma outra lógica deste serviço.

        Usa só campos que realmente existem em Demanda/Eleitor
        (protocolo = Demanda.id, título, status) — nunca CPF, endereço
        completo ou qualquer outro dado sensível além do necessário para
        o cidadão reconhecer a própria solicitação. O SIGAB nunca envia
        isto sozinho: é só o texto que aparece pronto dentro do WhatsApp,
        para o usuário do gabinete revisar e decidir se envia."""
        primeiro_nome = (nome_eleitor or "").strip().split(" ")[0] or nome_eleitor
        return (
            f"Olá, {primeiro_nome}. Aqui é do {nome_gabinete}.\n\n"
            f"Recebemos sua solicitação registrada sob o protocolo #{demanda_id}.\n\n"
            f"Assunto: {titulo}\n\n"
            f"Sua demanda está atualmente com o status: {status}.\n\n"
            "Estamos acompanhando sua solicitação."
        )
