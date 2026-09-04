"""Abstração de armazenamento de arquivos binários (hoje só as fotos
anexadas a Demandas via o atendimento público — ver
app/services/anexo_imagem_service.py e app/services/atendimento_publico_service.py).

Nenhum código fora deste módulo e do adapter concreto fala diretamente
com boto3/R2: tanto o fluxo público de upload quanto a visualização
interna do anexo (app/modules/demandas/controller.py) só conhecem esta
interface. Trocar de provedor de storage no futuro significa escrever um
novo adapter aqui, sem tocar em quem usa StorageService.
"""

from abc import ABC, abstractmethod

from app.core.config import settings


class StorageError(Exception):
    """Erro genérico de armazenamento — a mensagem nunca carrega detalhe
    de infraestrutura (endpoint, nome do bucket, credencial, erro bruto
    do boto3/botocore): quem captura esta exceção só pode repassar uma
    mensagem amigável ao usuário. O detalhe real de cada falha vai
    somente para o log do servidor (ver R2StorageAdapter)."""


class StorageService(ABC):
    """Interface mínima que qualquer provedor de storage precisa
    implementar. De propósito só tem os três verbos que o sistema
    realmente usa hoje — nenhum método especulativo."""

    @abstractmethod
    def armazenar(self, chave: str, conteudo: bytes, content_type: str) -> None:
        """Grava `conteudo` sob `chave`. Levanta StorageError em qualquer
        falha (nunca deixa vazar a exceção original do provedor)."""

    @abstractmethod
    def excluir(self, chave: str) -> None:
        """Remove o objeto em `chave`. Usado tanto pela compensação de
        upload parcial (ver AtendimentoPublicoService) quanto pela futura
        rotina de retenção (ainda não implementada nesta fase) — por isso
        é sempre "melhor esforço": uma falha aqui nunca deve interromper
        o fluxo que a chamou, só ser registrada em log."""

    @abstractmethod
    def gerar_url_temporaria(self, chave: str, validade_segundos: int = 300) -> str:
        """URL de leitura de curtíssima duração para `chave`. Só deve ser
        chamado depois que o chamador já validou que quem está pedindo
        tem permissão sobre o objeto (gabinete_id) — este método em si
        não valida nada, só assina a URL."""


def obter_storage_service() -> "StorageService | None":
    """Fábrica única do StorageService da aplicação. Retorna None quando o
    R2 não está configurado (nenhuma variável R2_* preenchida) — um valor
    explícito, não um erro mascarado: em ambiente local sem credenciais,
    o upload de fotos simplesmente fica indisponível (ver
    AtendimentoPublicoService, que trata None como "recusar com mensagem
    amigável" antes mesmo de tentar), enquanto o resto do sistema
    (demanda sem foto, e-mail diário, etc.) continua funcionando
    normalmente.

    Nunca cai de volta para um storage local em disco só para "fazer
    funcionar" sem R2 configurado — isso poderia ser confundido mais
    tarde com armazenamento de produção real. Testes automatizados que
    precisam simular upload usam um adapter fake próprio, injetado
    diretamente onde é preciso, nunca por aqui."""
    if not settings.r2_configurado:
        return None

    from app.services.r2_storage_adapter import R2StorageAdapter

    return R2StorageAdapter(
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket_name=settings.r2_bucket_name,
        endpoint=settings.r2_endpoint,
    )
