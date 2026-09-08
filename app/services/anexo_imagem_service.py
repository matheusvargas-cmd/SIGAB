"""Validação e reprocessamento das fotos enviadas pelo formulário público
(/cidadao/<public_token>) — sempre a última etapa de validação, antes de
qualquer upload para o R2 (ver AtendimentoPublicoService). Nenhum arquivo
chega ao storage sem passar por aqui primeiro:

1. quantidade (no máximo 3);
2. tamanho, por foto e no total, sobre os bytes originais enviados;
3. conteúdo real, decodificado com Pillow — nunca a extensão do nome do
   arquivo nem o Content-Type que o navegador declarou;
4. reprocessamento: correção de orientação (EXIF), redimensionamento sem
   upscale, conversão para WebP — a imagem original nunca é a que vai
   para o storage quando esta etapa é usada.
"""

import io
import re
import uuid
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image, ImageOps

MAX_FOTOS = 3
MAX_BYTES_POR_FOTO = 5 * 1024 * 1024
MAX_BYTES_TOTAL = 15 * 1024 * 1024
MAX_DIMENSAO_PX = 1600

# Guarda contra decompression bomb: além do próprio limite padrão do
# Pillow (Image.MAX_IMAGE_PIXELS, ~89 milhões de pixels — nunca desativado
# aqui), esta checagem explícita mais restritiva roda antes de qualquer
# decodificação de fato do conteúdo de pixel.
MAX_PIXELS = 40_000_000

FORMATOS_ACEITOS = {"JPEG", "PNG", "WEBP"}
_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS

ERRO_QUANTIDADE = "Você pode enviar no máximo 3 fotos."
ERRO_TAMANHO_INDIVIDUAL = "Cada foto pode ter no máximo 5 MB."
ERRO_TAMANHO_TOTAL = "As fotos não podem ultrapassar 15 MB no total."
ERRO_IMAGEM_INVALIDA = "Uma das fotos não é uma imagem válida."


@dataclass
class FotoProcessada:
    conteudo: bytes
    mime_type: str
    tamanho_bytes: int
    nome_original: str


def _sanitizar_nome_original(nome: str) -> str:
    """Guardado só como metadado em DemandaAnexo.nome_original — nunca
    usado para montar um caminho de arquivo/storage_key (essa chave é
    sempre gerada por gerar_storage_key, um uuid4 aleatório). Mesmo assim
    sanitizado, para nunca guardar algo como "../../arquivo.php" de forma
    que possa ser mal interpretado por qualquer código futuro que venha a
    lidar com este metadado: remove qualquer componente de diretório,
    restringe a um conjunto seguro de caracteres, limita o tamanho."""
    nome = (nome or "").strip()
    nome = nome.replace("\\", "/").split("/")[-1]
    nome = re.sub(r"[^A-Za-z0-9 ._-]", "_", nome)
    nome = nome.strip(" ._") or "foto"
    return nome[:150]


def validar_e_processar_fotos(fotos: list[UploadFile]) -> list[FotoProcessada]:
    """Lê e valida todas as fotos primeiro (quantidade, tamanho, conteúdo
    real) sem nenhum efeito colateral em banco/storage — só depois disso o
    chamador segue para criar a Demanda e efetivamente subir os arquivos
    (ver AtendimentoPublicoService.registrar_solicitacao). Levanta
    ValueError com uma das mensagens amigáveis acima; nunca deixa passar
    um arquivo que não seja de fato uma imagem JPEG/PNG/WebP
    decodificável."""
    # <input type="file" multiple> sem nenhuma foto selecionada não envia
    # nenhuma parte de arquivo — mas um filename vazio é descartado aqui
    # mesmo assim, defensivamente.
    fotos_validas = [foto for foto in fotos if foto is not None and (foto.filename or "").strip()]

    if len(fotos_validas) > MAX_FOTOS:
        raise ValueError(ERRO_QUANTIDADE)

    brutos: list[tuple[UploadFile, bytes]] = []
    total_bytes = 0
    for foto in fotos_validas:
        conteudo = foto.file.read()
        if not conteudo:
            continue
        if len(conteudo) > MAX_BYTES_POR_FOTO:
            raise ValueError(ERRO_TAMANHO_INDIVIDUAL)
        total_bytes += len(conteudo)
        brutos.append((foto, conteudo))

    if total_bytes > MAX_BYTES_TOTAL:
        raise ValueError(ERRO_TAMANHO_TOTAL)

    return [_processar_uma_foto(foto, conteudo) for foto, conteudo in brutos]


def _processar_uma_foto(foto: UploadFile, conteudo: bytes) -> FotoProcessada:
    # verify() checa a integridade estrutural do arquivo, mas invalida o
    # objeto Image para qualquer uso seguinte — por isso a imagem é
    # reaberta logo depois para o processamento de fato.
    try:
        verificacao = Image.open(io.BytesIO(conteudo))
        verificacao.verify()
    except Exception:
        raise ValueError(ERRO_IMAGEM_INVALIDA)

    try:
        imagem = Image.open(io.BytesIO(conteudo))
        if imagem.format not in FORMATOS_ACEITOS:
            raise ValueError(ERRO_IMAGEM_INVALIDA)
        if imagem.width * imagem.height > MAX_PIXELS:
            raise ValueError(ERRO_IMAGEM_INVALIDA)

        imagem = ImageOps.exif_transpose(imagem)

        tem_transparencia = imagem.mode in ("RGBA", "LA") or (
            imagem.mode == "P" and "transparency" in imagem.info
        )
        imagem = imagem.convert("RGBA" if tem_transparencia else "RGB")

        # thumbnail() nunca amplia (só reduz quando a imagem já é maior
        # que o limite) e preserva a proporção — exatamente o "nunca fazer
        # upscale" pedido.
        imagem.thumbnail((MAX_DIMENSAO_PX, MAX_DIMENSAO_PX), _RESAMPLE)

        # save() força a decodificação completa do pixel data (não só do
        # cabeçalho) — qualquer corrupção no meio do arquivo que verify()
        # não tivesse detectado cai aqui, no except genérico abaixo.
        buffer = io.BytesIO()
        imagem.save(buffer, format="WEBP", quality=82, method=4)
        conteudo_processado = buffer.getvalue()
    except ValueError:
        raise
    except Exception:
        raise ValueError(ERRO_IMAGEM_INVALIDA)

    return FotoProcessada(
        conteudo=conteudo_processado,
        mime_type="image/webp",
        tamanho_bytes=len(conteudo_processado),
        nome_original=_sanitizar_nome_original(foto.filename),
    )


def gerar_storage_key(gabinete_id: int, demanda_id: int) -> str:
    """Chave interna aleatória (uuid4) — nunca derivada de nome de
    arquivo, CPF, nome/e-mail/telefone do cidadão ou do public_token. O
    prefixo gabinetes/{id}/demandas/{id} mantém isolamento multi-tenant e
    por demanda mesmo dentro de um único bucket; o nome do arquivo em si é
    só um identificador aleatório, imprevisível."""
    return f"gabinetes/{gabinete_id}/demandas/{demanda_id}/{uuid.uuid4().hex}.webp"
