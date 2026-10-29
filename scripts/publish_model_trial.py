"""Publish a finished local trial as paired shared inventory/database folders."""
import argparse
import json
from pathlib import Path
from database_disaggregation.core.shared_runs import publish_trial


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trial',type=Path)
    args=parser.parse_args()
    print(json.dumps(publish_trial(args.trial),indent=2))
