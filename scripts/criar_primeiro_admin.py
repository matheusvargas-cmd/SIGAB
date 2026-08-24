"""Cria o primeiro Gabinete + Usuário ADMIN + vínculo MembroGabinete.

Uso (interativo, recomendado):

    python scripts/criar_primeiro_admin.py

O script pergunta o nome do gabinete, nome do usuário, e-mail e senha (a
senha é digitada com o terminal ocultando os caracteres — nunca aparece na
tela nem em nenhum log). Também semeia as categorias padrão para o
gabinete recém-criado, para que o cadastro de Demandas já tenha opções ao
abrir pela primeira vez.

Uso não interativo (ex.: automação de deploy/homologação) — define as
variáveis de ambiente abaixo antes de chamar o script; qualquer uma que
faltar cai de volta para o prompt interativo:

    SIGAB_BOOTSTRAP_GABINETE   nome do gabinete
    SIGAB_BOOTSTRAP_NOME       nome do usuário administrador
    SIGAB_BOOTSTRAP_EMAIL      e-mail de login (único)
    SIGAB_BOOTSTRAP_SENHA      senha (mínimo 8 caracteres)

Nenhuma senha padrão existe neste script nem em nenhum outro lugar do
código — é sempre fornecida por quem executa, nunca hardcoded. Rodar este
script mais de uma vez é seguro: se o e-mail já existir, o script avisa e
não faz nada (não cria usuário/gabinete duplicado).

Este é o único jeito de criar o primeiro administrador — não existe rota
HTTP nem usuário automático criado no boot da aplicação.

Em PostgreSQL (homologação/produção), rode `alembic upgrade head` ANTES
deste script — o schema não é criado automaticamente aqui (só em SQLite
local, mesma regra do main.py).
"""

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import gerar_hash_senha
from app.models.gabinete import Gabinete
from app.models.membro_gabinete import MembroGabinete
from app.models.usuario import Usuario
from app.services.migration_service import MigrationService

SENHA_MINIMO_CARACTERES = 8


def _obter(variavel_ambiente: str, pergunta: str, oculto: bool = False) -> str:
    valor = os.environ.get(variavel_ambiente, "").strip()
    if valor:
        return valor
    if oculto:
        return getpass.getpass(pergunta).strip()
    return input(pergunta).strip()


def main() -> int:
    print("=== SIGAB — criação do primeiro administrador ===\n")

    nome_gabinete = _obter("SIGAB_BOOTSTRAP_GABINETE", "Nome do gabinete: ")
    if len(nome_gabinete) < 2:
        print("Nome do gabinete inválido.")
        return 1

    nome_usuario = _obter("SIGAB_BOOTSTRAP_NOME", "Nome do administrador: ")
    if len(nome_usuario) < 2:
        print("Nome do usuário inválido.")
        return 1

    email = _obter("SIGAB_BOOTSTRAP_EMAIL", "E-mail de login: ").lower()
    if "@" not in email:
        print("E-mail inválido.")
        return 1

    senha = _obter("SIGAB_BOOTSTRAP_SENHA", "Senha (mínimo 8 caracteres): ", oculto=True)
    if len(senha) < SENHA_MINIMO_CARACTERES:
        print(f"Senha muito curta — mínimo {SENHA_MINIMO_CARACTERES} caracteres.")
        return 1
    if not os.environ.get("SIGAB_BOOTSTRAP_SENHA"):
        confirmacao = getpass.getpass("Confirme a senha: ").strip()
        if confirmacao != senha:
            print("As senhas não coincidem.")
            return 1

    # Só roda create_all() para SQLite local — a mesma regra do main.py.
    # Em PostgreSQL o schema é responsabilidade exclusiva do
    # `alembic upgrade head` rodado antes deste script; chamar create_all()
    # ali também, mesmo "só como garantia", poderia criar alguma tabela
    # direto a partir dos models atuais sem passar pela migração
    # correspondente — o schema real ficaria fora de sincronia com o
    # histórico do Alembic (`alembic_version`), o oposto do que a Fase 1
    # decidiu. Se as tabelas não existirem em PostgreSQL, é sinal de que o
    # `alembic upgrade head` ainda não rodou — o erro abaixo deve apontar
    # exatamente para isso, não ser mascarado por um create_all() silencioso.
    if settings.is_sqlite:
        Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        existente = db.scalar(select(Usuario).where(Usuario.email == email))
        if existente is not None:
            print(f"\nJá existe um usuário com o e-mail '{email}'. Nada foi criado.")
            return 1

        gabinete = Gabinete(nome=nome_gabinete, ativo=True)
        db.add(gabinete)
        db.flush()

        usuario = Usuario(
            nome=nome_usuario, email=email, senha_hash=gerar_hash_senha(senha), ativo=True
        )
        db.add(usuario)
        db.flush()

        membro = MembroGabinete(
            usuario_id=usuario.id, gabinete_id=gabinete.id, perfil="ADMIN", ativo=True
        )
        db.add(membro)
        db.commit()

        gabinete_id = gabinete.id

    MigrationService.semear_categorias_para_gabinete(gabinete_id)

    print("\nAdministrador criado com sucesso:")
    print(f"  Gabinete: {nome_gabinete} (id={gabinete_id})")
    print(f"  Usuário:  {nome_usuario} <{email}>")
    print("  Perfil:   ADMIN")
    print("\nJá é possível fazer login em /login com este e-mail e senha.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
