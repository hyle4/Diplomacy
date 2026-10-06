import os
from pathlib import Path

import uvicorn

from vengine.api import create_app

if __name__ == "__main__":
    os.environ.setdefault("VENGINE_PLUGIN_MODULES", "project_plugins")
    project_root = Path(__file__).parent
    uvicorn.run(create_app(project_root / "data", project_root=project_root),
                host="127.0.0.1", port=8765)
