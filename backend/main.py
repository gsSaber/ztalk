from __future__ import annotations

import os
import sys
from pathlib import Path
import uvicorn
from logger import *
from config import *

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    uvicorn.run(
        "app:app",
        host=get_config().backend.host,
        port=get_config().backend.port,
        factory=False,
    )


if __name__ == "__main__":
    main()
