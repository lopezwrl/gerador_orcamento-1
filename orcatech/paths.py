from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTANCE_DIR = PROJECT_ROOT / "instance"
CACHE_DIR = INSTANCE_DIR / "cache"
HISTORICO_FILE = INSTANCE_DIR / "historico.json"
PDF_DIR = INSTANCE_DIR / "orcamentos"
DEBUG_DIR = INSTANCE_DIR / "debug"

for directory in (INSTANCE_DIR, CACHE_DIR, PDF_DIR, DEBUG_DIR):
    directory.mkdir(parents=True, exist_ok=True)
