"""Generate the protected two-compiler reconstruction corpus."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'_app'))
from hivemind_assembly.domains.reverse_engineering.benchmarks import FAMILIES,HOLDOUT,generate

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output')
    print(json.dumps(generate(p.parse_args().output),indent=2))
