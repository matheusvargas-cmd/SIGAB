import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Em desenvolvimento (ou rodando via "uvicorn main:app"), BASE_DIR é a raiz
# do projeto, calculada a partir da localização deste arquivo — mesmo
# comportamento de sempre. Quando empacotado com PyInstaller (--onefile),
# sys.frozen existe e os arquivos (templates/static) ficam extraídos em
# sys._MEIPASS; usamos essa pasta como BASE_DIR nesse caso.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"

# O banco local nunca deve morar dentro do executável/pasta de instalação:
# no empacotado ele fica em %PROGRAMDATA%\Conecta360 (dado do usuário,
# sobrevive a reinstalações/atualizações do programa). Em desenvolvimento
# continua em <raiz do projeto>/database, como sempre foi. Isso só define
# o caminho do banco SQLite *padrão* — se DATABASE_URL vier de variável de
# ambiente (homologação/produção com PostgreSQL), esse caminho não é usado.
if getattr(sys, "frozen", False):
    DATABASE_DIR = Path(os.environ.get("PROGRAMDATA", Path.home())) / "Conecta360"
else:
    DATABASE_DIR = BASE_DIR / "database"
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

_DATABASE_URL_PADRAO_LOCAL = f"sqlite:///{DATABASE_DIR / 'sigab.db'}"


class Settings(BaseSettings):
    """Configuração por ambiente. Nenhum valor sensível tem default real —
    só defaults seguros para rodar local sem precisar criar um .env.

    Qualquer campo pode ser sobrescrito por variável de ambiente (mesmo
    nome, maiúsculo ou minúsculo) ou por um arquivo .env na raiz do
    projeto (nunca versionado — ver .env.example para o modelo).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ambiente: Literal["local", "homologacao", "producao"] = "local"

    # Sem valor de ambiente definido, cai no SQLite local de sempre — o
    # comportamento atual continua idêntico sem exigir nenhum .env.
    database_url: str = _DATABASE_URL_PADRAO_LOCAL

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalizar_dialeto_postgres(cls, valor: str) -> str:
        """Provedores gerenciados (Neon via Render, entre outros) entregam a
        DATABASE_URL como "postgresql://..." ou "postgres://..." — o formato
        genérico do protocolo, sem indicar driver. Sem o "+psycopg" depois do
        dialeto, o SQLAlchemy assume psycopg2 (o driver padrão histórico de
        "postgresql://"), que este projeto nunca instala de propósito — usa
        psycopg 3 (pacote "psycopg[binary]"). Normalizar aqui, uma vez, no
        carregamento da configuração, evita reescrever a URL em cada lugar
        que abre conexão (database.py, migrations/env.py) e evita adicionar
        psycopg2 só para mascarar o formato que a infraestrutura entrega.
        Só reescreve o prefixo genérico exato — uma URL que já diz o driver
        (ex.: "postgresql+psycopg://", ou qualquer outro "postgresql+...://")
        passa direto, sem alteração; usuário, senha, host e parâmetros nunca
        são tocados.
        """
        if valor.startswith("postgres://"):
            return "postgresql+psycopg://" + valor[len("postgres://") :]
        if valor.startswith("postgresql://"):
            return "postgresql+psycopg://" + valor[len("postgresql://") :]
        return valor

    # Usada para assinar cookies de sessão quando a autenticação existir.
    # O valor abaixo só é seguro em ambiente=local; ver _validar_producao().
    secret_key: str = "dev-insecure-change-me"

    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000

    # Tempo de vida da sessão de login (cookie assinado) — passado direto
    # como max_age do SessionMiddleware. 12h cobre um expediente sem exigir
    # login de novo, sem deixar uma sessão válida por semanas num
    # computador compartilhado do gabinete.
    sessao_max_idade_horas: int = 12

    @property
    def sessao_max_idade_segundos(self) -> int:
        return self.sessao_max_idade_horas * 3600

    # Lista de origens permitidas para CORS, separadas por vírgula.
    # Vazio (padrão) = nenhuma origem externa liberada — correto para um
    # app renderizado no servidor, sem frontend separado consumindo API.
    cors_origins: str = ""

    log_level: str = "INFO"

    # --- E-mail diário do gabinete (app/services/daily_email_service.py) ---
    # Nenhum provedor específico é assumido: qualquer SMTP compatível
    # (Gmail com senha de app, SendGrid, Mailgun, SES etc.) funciona só
    # trocando essas variáveis. Todas com default vazio/seguro — ambiente
    # local continua funcionando sem nenhuma delas definida (o envio de
    # e-mail simplesmente não roda sem configuração, nunca quebra o boot).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    @property
    def smtp_configurado(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    # Token secreto para a rota POST /jobs/enviar-diario (chamada por um
    # agendador externo, nunca por um usuário logado — não usa cookie de
    # sessão). Vazio por padrão: a rota recusa qualquer chamada enquanto
    # este valor não for definido, então não existe um "token padrão"
    # esquecido em produção.
    jobs_token: str = ""

    @property
    def cors_origins_lista(self) -> list[str]:
        return [origem.strip() for origem in self.cors_origins.split(",") if origem.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cookie_secure(self) -> bool:
        # Cookie "Secure" exige HTTPS — correto em homologação/produção
        # (sempre atrás de HTTPS), mas local roda em http://127.0.0.1 sem
        # TLS, então o cookie precisa aceitar HTTP aí ou o login nunca
        # persistiria em desenvolvimento.
        return self.ambiente != "local"

    def validar_producao(self) -> list[str]:
        """Checagens de sanidade para homologação/produção que não impedem
        o boot por si só (avisos para o logger reportar alto e claro no
        startup). As checagens que realmente impedem o boot — SECRET_KEY
        insegura e SQLite fora de local — estão em `exigir_secret_key_segura()`
        e `exigir_banco_gerenciado_fora_de_local()`, chamadas antes desta."""
        avisos = []
        if self.ambiente != "local":
            if self.debug:
                avisos.append(f"DEBUG=true em ambiente={self.ambiente!r} — desative fora de local.")
        return avisos

    def exigir_secret_key_segura(self) -> None:
        """Fora de ambiente=local, uma SECRET_KEY previsível (o valor de
        desenvolvimento, ou vazia) permite a qualquer um forjar um cookie de
        sessão assinado — login como qualquer usuário, em qualquer gabinete,
        sem senha. Isso é grave o bastante para interromper o boot em vez de
        só avisar (diferente de validar_producao() acima)."""
        if self.ambiente == "local":
            return
        if not self.secret_key or self.secret_key == "dev-insecure-change-me":
            raise RuntimeError(
                f"SECRET_KEY ainda é o valor de desenvolvimento em ambiente={self.ambiente!r}. "
                "Defina uma chave própria (ex.: `python -c \"import secrets; "
                'print(secrets.token_hex(32))"`) na variável de ambiente SECRET_KEY '
                "antes de subir este ambiente — a aplicação não inicia sem isso."
            )

    def exigir_banco_gerenciado_fora_de_local(self) -> None:
        """Fora de ambiente=local, DATABASE_URL tem que apontar para o
        PostgreSQL do ambiente (Fase 3: 'PostgreSQL obrigatório' em
        homologação e produção) — nunca cair de volta no SQLite padrão só
        porque a variável de ambiente foi esquecida. Interrompe o boot pelo
        mesmo motivo que a SECRET_KEY: rodar homologação/produção sem o
        banco certo não é um detalhe de configuração, é usar a infraestrutura
        errada por engano."""
        if self.ambiente == "local":
            return
        if self.is_sqlite:
            raise RuntimeError(
                f"ambiente={self.ambiente!r} está usando SQLite — defina DATABASE_URL "
                "apontando para o PostgreSQL do ambiente (ex.: "
                "postgresql+psycopg://usuario:senha@host/banco?sslmode=require) "
                "antes de subir este ambiente — a aplicação não inicia sem isso."
            )


settings = Settings()

# Mantidos como constantes de nível de módulo por compatibilidade com todo
# o código existente (controllers, database.py, launcher) que já importa
# esses nomes diretamente — nenhum import precisa mudar.
DATABASE_URL = settings.database_url
APP_NAME = "Gabinete 360"
APP_TAGLINE = "Gestão Inteligente de Gabinetes"
