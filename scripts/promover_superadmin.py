"""Promove um usuário já existente a SUPERADMIN.

Uso (interativo, recomendado):

    python scripts/promover_superadmin.py

O script pergunta o e-mail do usuário a promover. Não cria usuário novo —
o e-mail precisa já existir (criado antes via scripts/criar_primeiro_admin.py
ou pela interface). Não pede nem aceita senha: SUPERADMIN usa a mesma senha
que o usuário já tem, só ganha o flag global `super_admin=True`.

Uso não interativo (ex.: shell do Render) — definir antes de chamar:

    SIGAB_PROMOVER_SUPERADMIN_EMAIL   e-mail do usuário a promover

Idempotente: se o usuário já for SUPERADMIN, avisa e não faz nada.
Nenhum e-mail ou senha fica hardcoded neste script nem em nenhum outro
lugar do código — quem promove alguém decide isso explicitamente, a cada
execução.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.usuario import Usuario


def _obter(variavel_ambiente: str, pergunta: str) -> str:
    valor = os.environ.get(variavel_ambiente, "").strip()
    if valor:
        return valor
    return input(pergunta).strip()


def main() -> int:
    print("=== Gabinete 360 — promover SUPERADMIN ===\n")

    email = _obter("SIGAB_PROMOVER_SUPERADMIN_EMAIL", "E-mail do usuário a promover: ").lower()
    if "@" not in email:
        print("E-mail inválido.")
        return 1

    with SessionLocal() as db:
        usuario = db.scalar(select(Usuario).where(Usuario.email == email))
        if usuario is None:
            print(f"\nNenhum usuário encontrado com o e-mail '{email}'.")
            print("Este script não cria usuário novo — crie a conta antes")
            print("(scripts/criar_primeiro_admin.py ou pela interface) e rode de novo.")
            return 1

        if usuario.super_admin:
            print(f"\n'{usuario.nome}' <{email}> já é SUPERADMIN. Nada foi alterado.")
            return 0

        usuario.super_admin = True
        nome = usuario.nome
        db.commit()

    print(f"\n'{nome}' <{email}> agora é SUPERADMIN.")
    print("Já é possível fazer login em /login com este e-mail e a senha já existente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
