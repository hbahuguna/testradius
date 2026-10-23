import sys
from pathlib import Path

# The rule-engine tests import sibling modules directly. Pytest normally inserts this
# directory, but being explicit keeps `-c apps/cell/pyproject.toml` from changing it.
sys.path.insert(0, str(Path(__file__).parent))
