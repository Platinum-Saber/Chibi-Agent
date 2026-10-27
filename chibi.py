"""Start Raphael: runs the agent, which starts Ollama, the overlay and the voice process.

    python chibi.py

Each package has its own venv (`uv sync` in agent/, overlay/ and voice/).
"""
import subprocess
import sys
from pathlib import Path

AGENT = Path(__file__).parent / "agent"
PY = AGENT / ".venv" / "Scripts" / "python.exe"

if not PY.exists():
    sys.exit(f"No agent venv. Run:  cd {AGENT} && uv sync")
try:
    sys.exit(subprocess.call([str(PY), "-m", "chibi_agent"], cwd=AGENT))
except KeyboardInterrupt:
    pass
