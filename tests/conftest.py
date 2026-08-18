"""Put the repo root on sys.path so tests can import top-level packages
(options/, ...). Older tests insert their own paths and are unaffected."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
