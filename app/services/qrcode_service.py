"""Geração de QR Code do link público do gabinete (ver
app/modules/gabinete/controller.py). Só sabe transformar um texto (a URL
já pronta, montada por GabineteService.montar_url_publica) em uma imagem
PNG — não conhece Gabinete, token nem domínio."""

import io

import qrcode


class QrCodeService:
    @staticmethod
    def gerar_png(conteudo: str) -> bytes:
        imagem = qrcode.make(conteudo, box_size=10, border=4)
        buffer = io.BytesIO()
        imagem.save(buffer, format="PNG")
        return buffer.getvalue()
