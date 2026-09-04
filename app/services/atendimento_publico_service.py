from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.demanda import Demanda
from app.models.demanda_anexo import DemandaAnexo
from app.models.gabinete import Gabinete
from app.models.submissao_cidadao import SubmissaoCidadao
from app.services.anexo_imagem_service import (
    FotoProcessada,
    gerar_storage_key,
    validar_e_processar_fotos,
)
from app.services.demanda_service import DemandaService
from app.services.eleitor_service import EleitorService
from app.services.storage_service import obter_storage_service

NOME_MINIMO_CARACTERES = 2

ERRO_FALHA_ANEXO = "Não foi possível anexar as fotos. Tente novamente."


class SolicitacaoEmProcessamentoError(Exception):
    """O token de submissão já foi reivindicado por outra requisição, mas
    a Demanda dela ainda não existe (janela muito estreita entre o INSERT
    da reivindicação e a criação da Demanda — ver
    registrar_solicitacao_idempotente). Nunca cria uma segunda Demanda
    nesse caso; o chamador decide o que mostrar (mensagem amigável para
    tentar de novo)."""


class AtendimentoPublicoService:
    """Orquestra o fluxo do módulo público (/cidadao/<public_token>):
    CPF -> Eleitor (existente ou novo) -> DemandaService -> Demanda normal
    do SIGAB, com origem="PUBLICA". Não reimplementa nenhuma regra que já
    existe em EleitorService/DemandaService — só decide QUAIS métodos
    chamar e QUAIS valores o cidadão NUNCA pode determinar (gabinete_id,
    status, prioridade, origem, responsável, secretaria), que aqui são
    sempre fixos/derivados do servidor, nunca lidos do formulário."""

    @staticmethod
    def registrar_solicitacao_idempotente(
        db: Session, gabinete: Gabinete, submissao_token: str, **campos
    ) -> tuple[Demanda, bool]:
        """Ponto de entrada usado pelo controller — envolve
        registrar_solicitacao() com a trava de idempotência. Retorna
        (demanda, reaproveitada): reaproveitada=True quando o token já
        tinha sido usado antes com sucesso (reenvio/corrida) e nenhuma
        Demanda nova foi criada desta vez.

        A reivindicação (INSERT + commit imediato) acontece ANTES da
        validação de negócio (CPF, categoria etc.), que só roda dentro de
        registrar_solicitacao(). Se essa validação falhar (ValueError), a
        reivindicação já feita fica órfã (demanda_id nunca é preenchido)
        — de propósito não há rollback dela aqui: desfazer a
        reivindicação abriria uma segunda janela de corrida (entre
        apagar a linha e permitir reuso do mesmo token). É responsabilidade
        do controller, ao capturar ValueError, gerar um novo
        submissao_token para a próxima tentativa — nunca reoferecer o
        token que acabou de falhar. A unicidade em SubmissaoCidadao.token
        é quem de fato serializa duas requisições concorrentes; ver
        docstring do model."""
        reivindicacao = SubmissaoCidadao(token=submissao_token, gabinete_id=gabinete.id)
        db.add(reivindicacao)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existente = db.scalar(
                select(SubmissaoCidadao).where(
                    SubmissaoCidadao.token == submissao_token,
                    SubmissaoCidadao.gabinete_id == gabinete.id,
                )
            )
            if existente is not None and existente.demanda_id is not None:
                demanda_existente = db.get(Demanda, existente.demanda_id)
                if demanda_existente is not None and demanda_existente.gabinete_id == gabinete.id:
                    return demanda_existente, True
            # Token já reivindicado, mas a Demanda ainda não foi gravada
            # (a outra requisição está terminando de processar agora) ou
            # pertence a outro gabinete (nunca deveria acontecer com um
            # token de 256 bits, mas nunca confiar cegamente) — em
            # qualquer um desses casos, não criar Demanda nenhuma aqui.
            raise SolicitacaoEmProcessamentoError(
                "Esta solicitação já está sendo processada. Aguarde um instante."
            )

        demanda = AtendimentoPublicoService.registrar_solicitacao(db, gabinete, **campos)
        reivindicacao.demanda_id = demanda.id
        db.commit()
        return demanda, False

    @staticmethod
    def registrar_solicitacao(
        db: Session,
        gabinete: Gabinete,
        nome: str,
        cpf: str,
        whatsapp: str,
        telefone: str | None,
        email: str | None,
        cep: str | None,
        logradouro: str | None,
        numero: str | None,
        complemento: str | None,
        bairro: str | None,
        cidade: str | None,
        categoria_id: str | None,
        subcategoria_id: str | None,
        titulo: str,
        descricao: str,
        fotos: list[UploadFile] | None = None,
    ) -> Demanda:
        nome_normalizado = (nome or "").strip()
        if len(nome_normalizado) < NOME_MINIMO_CARACTERES:
            raise ValueError("Informe seu nome completo.")

        if not (whatsapp or "").strip():
            raise ValueError("Informe um WhatsApp para contato.")

        if not (titulo or "").strip():
            raise ValueError("Informe o assunto da sua solicitação.")

        if not (descricao or "").strip():
            raise ValueError("Descreva sua solicitação.")

        # Fotos são validadas (quantidade, tamanho, conteúdo real) antes
        # de qualquer escrita em Eleitor/Demanda — nunca criar a demanda
        # para só depois descobrir que uma foto é inválida. Se há foto mas
        # o storage não está configurado neste ambiente (ver
        # app/services/storage_service.py), recusa aqui mesmo, com a
        # mesma mensagem amigável de falha de upload — nunca cria a
        # demanda sem conseguir cumprir o que foi pedido.
        fotos_processadas = validar_e_processar_fotos(fotos or [])
        if fotos_processadas and obter_storage_service() is None:
            raise ValueError(ERRO_FALHA_ANEXO)

        # endereco: o model Eleitor só tem um campo de texto livre para
        # endereço (sem CEP/logradouro/número/complemento estruturados —
        # nenhuma tela do SIGAB, interna ou pública, teria onde exibir
        # esses campos separadamente hoje). Combinados aqui num único
        # texto legível para não perder nenhuma informação que o cidadão
        # digitou, sem precisar de uma migration para esta etapa.
        endereco = AtendimentoPublicoService._montar_endereco(cep, logradouro, numero, complemento)

        # CPF é a chave — cria ou reaproveita o eleitor deste gabinete.
        # criar_ou_atualizar_por_cpf já valida o CPF (dígito verificador)
        # e nunca apaga um campo cadastral existente só porque este envio
        # não trouxe valor para ele.
        eleitor = EleitorService.criar_ou_atualizar_por_cpf(
            db,
            gabinete.id,
            cpf=cpf,
            nome=nome_normalizado,
            whatsapp=whatsapp,
            telefone=telefone,
            email=email,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
        )

        # DemandaService.criar (via _validar_dados) já garante que
        # categoria_id/subcategoria_id pertencem a este gabinete — é a
        # mesma validação usada pelo formulário interno, reaproveitada
        # aqui sem duplicar nenhuma regra. status/prioridade/origem nunca
        # vêm do formulário público: são sempre estes três valores fixos.
        #
        # commit=False: a Demanda só fica definitivamente gravada junto
        # com seus DemandaAnexo (ver abaixo) — nunca uma Demanda comitada
        # sem se saber ainda se as fotos foram enviadas com sucesso, nem
        # anexos comitados sem a Demanda que eles referenciam.
        demanda = DemandaService.criar(
            db,
            gabinete.id,
            eleitor_id=str(eleitor.id),
            titulo=titulo,
            descricao=descricao,
            categoria_id=categoria_id,
            subcategoria_id=subcategoria_id,
            status="Protocolado",
            prioridade="Normal",
            origem="PUBLICA",
            commit=False,
        )

        if not fotos_processadas:
            db.commit()
            db.refresh(demanda)
            return demanda

        # R2 e o banco não são uma transação distribuída única — a
        # sequência abaixo é a compensação possível sem uma arquitetura
        # distribuída complexa: primeiro sobe TODOS os objetos (nada é
        # gravado em DemandaAnexo ainda); só depois de todos terem tido
        # sucesso é que as linhas de metadado são criadas e tudo é
        # comitado junto. Se qualquer etapa falhar (upload ou commit),
        # todo objeto já enviado ao R2 nesta tentativa é excluído
        # (melhor esforço) e a sessão de banco é revertida — nunca fica
        # "Demanda criada, sem se saber se tem foto" nem "foto no R2 sem
        # nenhum registro em DemandaAnexo". A única janela residual não
        # coberta é uma falha simultânea do commit E da exclusão de
        # compensação (ver limitação documentada no relatório).
        storage = obter_storage_service()
        chaves_enviadas: list[tuple[str, FotoProcessada]] = []
        try:
            for foto_processada in fotos_processadas:
                chave = gerar_storage_key(gabinete.id, demanda.id)
                storage.armazenar(chave, foto_processada.conteudo, foto_processada.mime_type)
                chaves_enviadas.append((chave, foto_processada))

            for chave, foto_processada in chaves_enviadas:
                db.add(
                    DemandaAnexo(
                        demanda_id=demanda.id,
                        gabinete_id=gabinete.id,
                        storage_key=chave,
                        nome_original=foto_processada.nome_original,
                        mime_type=foto_processada.mime_type,
                        tamanho_bytes=foto_processada.tamanho_bytes,
                        arquivo_disponivel=True,
                    )
                )
            db.commit()
        except Exception:
            for chave, _ in chaves_enviadas:
                storage.excluir(chave)
            db.rollback()
            raise ValueError(ERRO_FALHA_ANEXO)

        db.refresh(demanda)
        return demanda

    @staticmethod
    def _montar_endereco(
        cep: str | None, logradouro: str | None, numero: str | None, complemento: str | None
    ) -> str | None:
        partes = []
        if logradouro and logradouro.strip():
            partes.append(logradouro.strip())
        if numero and numero.strip():
            partes.append(f"nº {numero.strip()}")
        if complemento and complemento.strip():
            partes.append(complemento.strip())
        linha = ", ".join(partes)
        if cep and cep.strip():
            linha = f"{linha} — CEP {cep.strip()}" if linha else f"CEP {cep.strip()}"
        return linha or None
