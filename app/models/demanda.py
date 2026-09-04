from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Demanda(Base):
    __tablename__ = "demandas"

    id = Column(Integer, primary_key=True)

    # Nullable por enquanto: dado existente (local, pré multi-tenant) não
    # tem gabinete atribuído ainda. Ver documento de arquitetura, seção 8.
    gabinete_id = Column(Integer, ForeignKey("gabinetes.id"), nullable=True, index=True)

    # nullable: o sistema de origem (Meu Mandato) permite demanda sem
    # eleitor vinculado (ex.: "Ref. eleitor" vazio, ou "Eleitor" = nome do
    # próprio gabinete) — ver DemandaCsvService.importar_atendimento_historico.
    # O formulário manual continua exigindo eleitor (DemandaService.criar
    # valida isso por padrão; só a importação histórica passa eleitor_obrigatorio=False).
    eleitor_id = Column(Integer, ForeignKey("eleitores.id"), nullable=True)
    eleitor = relationship("Eleitor")

    titulo = Column(String(150), nullable=False)

    descricao = Column(Text)

    categoria = Column(String(60))

    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    categoria_vinculada = relationship("Categoria")

    subcategoria_id = Column(Integer, ForeignKey("subcategorias.id"), nullable=True)
    subcategoria_vinculada = relationship("Subcategoria")

    status = Column(String(40), default="Protocolado")

    secretaria = Column(String(100))

    prioridade = Column(String(30), default="Normal")

    responsavel = Column(String(150))

    data_abertura = Column(DateTime)

    prazo = Column(Date)

    data_fechamento = Column(DateTime)

    observacoes_internas = Column(Text)

    ref_historico = Column(String(50))

    # Origem da demanda: "INTERNA" (cadastrada por alguém do gabinete,
    # sempre foi o único caso até agora) ou "PUBLICA" (futuro módulo de
    # Atendimento ao Cidadão, /cidadao/<token> — ainda não implementado
    # nesta fase). default="INTERNA" cobre todo INSERT que não informar o
    # campo explicitamente — nenhuma chamada existente de
    # DemandaService.criar precisa mudar por causa disso.
    origem = Column(String(20), nullable=False, default="INTERNA")