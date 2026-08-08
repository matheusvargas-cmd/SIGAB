from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent.parent
DATABASE_DIR=BASE_DIR/"database"
DATABASE_DIR.mkdir(exist_ok=True)
DATABASE_URL=f"sqlite:///{DATABASE_DIR/'sigab.db'}"
APP_NAME="SIGAB"
