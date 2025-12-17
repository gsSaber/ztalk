from pathlib import Path
import logging
from datetime import datetime

_log_dir = Path(__file__).resolve().parents[2] / "zht_talk_logs"
_log_dir.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
_log_file = f"{_log_dir}/{timestamp}.log"

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
	handlers=[
		logging.FileHandler(_log_file, encoding="utf-8"),
		logging.StreamHandler(),
	],
)

logger = logging.getLogger("zht_talk")



__all__ = ["logger"]