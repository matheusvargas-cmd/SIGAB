import os
import sys
from pathlib import Path

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

# O banco nunca deve morar dentro do executável/pasta de instalação: no
# empacotado ele fica em %PROGRAMDATA%\Conecta360 (dado do usuário,
# sobrevive a reinstalações/atualizações do programa). Em desenvolvimento
# continua em <raiz do projeto>/database, como sempre foi.
if getattr(sys, "frozen", False):
    DATABASE_DIR = Path(os.environ.get("PROGRAMDATA", Path.home())) / "Conecta360"
else:
    DATABASE_DIR = BASE_DIR / "database"
DATABASE_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATABASE_DIR/'sigab.db'}"
APP_NAME = "Conecta 360"
APP_TAGLINE = "Gestão Inteligente de Gabinetes"
