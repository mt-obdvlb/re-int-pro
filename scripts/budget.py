"""Inspect charges or explicitly reconcile unknown fees against a provider bill."""

import argparse
import json

from probeops.config import settings
from probeops.storage import Store
from probeops.telemetry import Telemetry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--charge")
    parser.add_argument("--actual-micro-cny", type=int)
    parser.add_argument("--bill-reference")
    args = parser.parse_args()
    config = settings()
    telemetry = Telemetry(config.probeops_telemetry_dir, "budget")
    store = Store(config.probeops_db_path, telemetry, config)
    try:
        if args.charge:
            if args.actual_micro_cny is None or not args.bill_reference:
                parser.error("Reconciliation requires actual fee and bill reference")
            store.reconcile(args.charge, args.actual_micro_cny, args.bill_reference)
        with store.connection() as db:
            unknown = [
                dict(r)
                for r in db.execute("SELECT id,run_id,amount FROM charges WHERE state='uncertain'")
            ]
        print(json.dumps({"budget": store.budget(), "uncertain": unknown}, ensure_ascii=False))
    finally:
        telemetry.close()


if __name__ == "__main__":
    main()
