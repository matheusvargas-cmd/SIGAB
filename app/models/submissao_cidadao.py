from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class SubmissaoCidadao(Base):
    """Trava de idempotência do formulário público (/cidadao/<token>) —
    existe só para impedir que duas requisições POST quase simultâneas
    (duplo clique, F5 numa janela de corrida) criem duas Demandas a
    partir do mesmo envio.

    Por que não basta sessão/cookie: cada requisição concorrente enxerga
    seu próprio cookie (o navegador manda o mesmo cookie nas duas), então
    um teste "if token not in session" nas duas ao mesmo tempo passaria
    nas duas — não serializa nada. A garantia real vem da UNIQUE
    constraint em `token`: a segunda requisição que tentar inserir o
    mesmo token recebe um IntegrityError do próprio banco (PostgreSQL
    bloqueia a segunda até a primeira confirmar/desfazer; SQLite serializa
    por ser single-writer) — é o SGBD, não a aplicação, quem decide qual
    das duas chega primeiro.

    token nunca é gabinete_id/eleitor_id/demanda_id nem derivado deles —
    sempre secrets.token_urlsafe, gerado ao renderizar o formulário
    (GET), reivindicado (INSERT) só no POST, uma vez só. gabinete_id
    aqui é sobre QUEM pode reivindicar/consultar este token (nunca usado
    para localizar Gabinete — isso continua sendo só o public_token da
    URL), e é o que impede um token de um gabinete confirmar a
    solicitação de outro."""

    __tablename__ = "submissoes_cidadao"

    id = Column(Integer, primary_key=True)

    token = Column(String(64), nullable=False, unique=True, index=True)

    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=False, index=True)
    gabinete = relationship("Gabinete")

    # NULL enquanto a demanda ainda não foi criada (mesma requisição que
    # reivindicou o token, entre o INSERT desta linha e a criação da
    # Demanda) — só usado por uma reivindicação concorrente perdedora
    # para decidir se já existe um protocolo pronto para reaproveitar.
    demanda_id = Column(Integer, ForeignKey("demandas.id"), nullable=True)
    demanda = relationship("Demanda")

    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
