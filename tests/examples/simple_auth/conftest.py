import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
sys.path[:0] = [
    str(REPOSITORY_ROOT / "examples" / "clients" / "simple-auth-client"),
    str(REPOSITORY_ROOT / "examples" / "servers" / "simple-auth"),
]
