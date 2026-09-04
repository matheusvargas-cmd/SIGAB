"""Implementação de StorageService para Cloudflare R2, via boto3 (a API
do R2 é compatível com S3 — nenhuma biblioteca artesanal de HTTP).

O bucket é sempre privado (Public Access = Disabled no painel do R2) —
este adapter nunca gera um link público permanente, só URLs pré-assinadas
de curtíssima duração (gerar_url_temporaria), e mesmo essas só devem ser
pedidas depois que o chamador já validou gabinete_id (ver
app/modules/demandas/controller.py). Nenhuma credencial, endpoint ou nome
de bucket aparece em qualquer mensagem que chega ao usuário — só nos logs
do servidor, e mesmo aí nunca a chave secreta em si (boto3 nunca loga
aws_secret_access_key nas mensagens de exceção que capturamos aqui)."""

import logging

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.services.storage_service import StorageError, StorageService

logger = logging.getLogger(__name__)


class R2StorageAdapter(StorageService):
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        endpoint: str,
    ) -> None:
        self._bucket = bucket_name
        self._cliente = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

    def armazenar(self, chave: str, conteudo: bytes, content_type: str) -> None:
        try:
            self._cliente.put_object(
                Bucket=self._bucket,
                Key=chave,
                Body=conteudo,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError):
            logger.exception("Falha ao enviar objeto para o R2 (chave=%s).", chave)
            raise StorageError("Não foi possível enviar o arquivo para o armazenamento.")

    def excluir(self, chave: str) -> None:
        try:
            self._cliente.delete_object(Bucket=self._bucket, Key=chave)
        except (BotoCoreError, ClientError):
            # Melhor esforço — normalmente chamado durante uma compensação
            # (limpeza de objeto já enviado após outra falha). Uma exceção
            # aqui nunca deve mascarar o erro original que disparou a
            # limpeza, por isso só registra em log e segue.
            logger.exception("Falha ao excluir objeto do R2 (chave=%s).", chave)

    def gerar_url_temporaria(self, chave: str, validade_segundos: int = 300) -> str:
        try:
            return self._cliente.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": chave},
                ExpiresIn=validade_segundos,
            )
        except (BotoCoreError, ClientError):
            logger.exception("Falha ao gerar URL temporária do R2 (chave=%s).", chave)
            raise StorageError("Não foi possível gerar o link de acesso ao arquivo.")
