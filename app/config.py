import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
# Papercut's library (D:\Read\library): read-only, for what the course's papers say
PAPERCUT_LIBRARY = Path(os.environ.get("ALMANAC_PAPERCUT_LIBRARY", ROOT.parent / "library")).resolve()
DB_PATH =Path(os.environ.get("ALMANAC_DB", ROOT / "data" / "almanac.db")).resolve()
