import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DB_PATH = Path(os.environ.get("ALMANAC_DB", ROOT / "data" / "almanac.db")).resolve()
