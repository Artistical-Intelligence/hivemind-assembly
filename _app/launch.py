"""Entry point compatible with isolated Windows embedded Python."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from hivemind_assembly.__main__ import main
main()
