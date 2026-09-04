import re


def normalizar_cpf(cpf: str | None) -> str | None:
    """Remove tudo que não é dígito ("123.456.789-09" -> "12345678909").
    Retorna None se não sobrar nenhum dígito — nunca uma string vazia, para
    que a coluna cpf_normalizado se comporte como "sem CPF" (compatível
    com a constraint de unicidade parcial, que ignora NULL) em vez de um
    valor "" que colidiria entre eleitores diferentes sem CPF nenhum.

    Não valida quantidade de dígitos nem dígito verificador — só
    normaliza formatação para comparação. Um CPF de fato inválido
    continua sendo armazenado (não é papel desta função rejeitar dado
    histórico), só deixa de ser comparável a outro CPF por causa de
    pontuação diferente."""
    if not cpf:
        return None
    digitos = re.sub(r"\D", "", cpf)
    return digitos or None


def validar_cpf(cpf_normalizado: str | None) -> bool:
    """Validação matemática real (dígitos verificadores) — normalizar_cpf()
    acima NUNCA validou, só normaliza formatação; esta função existe
    separada de propósito, para não mudar o comportamento de quem já
    chama normalizar_cpf() só para comparar/armazenar (ex.:
    EleitorService.criar/atualizar, usado pelo cadastro manual interno,
    que nunca exigiu CPF válido). Só o atendimento público (que EXIGE CPF
    válido) chama validar_cpf().

    Espera a string já normalizada (só dígitos, ver normalizar_cpf).
    Rejeita: tamanho diferente de 11, sequências repetidas (ex.
    "111.111.111-11" — matematicamente "passariam" no cálculo do dígito
    verificador, mas nunca são CPFs reais) e dígitos verificadores
    incorretos."""
    if not cpf_normalizado or len(cpf_normalizado) != 11 or not cpf_normalizado.isdigit():
        return False
    if cpf_normalizado == cpf_normalizado[0] * 11:
        return False

    def _digito_verificador(base: str) -> int:
        soma = sum(int(digito) * peso for digito, peso in zip(base, range(len(base) + 1, 1, -1)))
        resto = (soma * 10) % 11
        return 0 if resto == 10 else resto

    primeiro_digito = _digito_verificador(cpf_normalizado[:9])
    segundo_digito = _digito_verificador(cpf_normalizado[:9] + str(primeiro_digito))
    return cpf_normalizado[-2:] == f"{primeiro_digito}{segundo_digito}"
