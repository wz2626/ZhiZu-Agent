"""Start the local server, even when invoked outside the repository directory."""

import sys
from pathlib import Path

import uvicorn


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
