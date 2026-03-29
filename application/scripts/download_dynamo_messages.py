"""
Download all messages from the DynamoDB messages table to local JSON and CSV files.

Usage:
  cd application
  python scripts/download_dynamo_messages.py                # uses MESSAGES_TABLE from .env
  python scripts/download_dynamo_messages.py --table MyTable # override table name
  python scripts/download_dynamo_messages.py --region us-west-2

Env vars:
  MESSAGES_TABLE   DynamoDB table name (or pass --table)
  AWS_REGION       AWS region (default: us-east-1, or pass --region)
  AWS credentials  via env, profile, or IAM role
"""

import argparse
import csv
import json
import logging
import os
import sys
from decimal import Decimal

_script_dir = os.path.dirname(os.path.abspath(__file__))
_application_dir = os.path.dirname(_script_dir)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(_application_dir, ".env"))
load_dotenv(os.path.join(os.path.dirname(_application_dir), ".env"), override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """Handle Decimal values from DynamoDB."""
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o == int(o) else float(o)
        return super().default(o)


def scan_table(table_name: str, region: str) -> list[dict]:
    """Full scan of a DynamoDB table. Returns all items."""
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    items = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
        log.info("Scanned %d items so far...", len(items))

    log.info("Scan complete: %d items total.", len(items))
    return items


def write_json(items: list[dict], path: str):
    with open(path, "w") as f:
        json.dump(items, f, indent=2, cls=DecimalEncoder, ensure_ascii=False)
    log.info("JSON written to %s", path)


def write_csv(items: list[dict], path: str):
    if not items:
        return
    fieldnames = ["sessionId", "msgId", "timestamp", "userQuery", "responseContent", "source", "reaction", "userComment"]
    # Include any extra fields not in the default list
    all_keys = set()
    for item in items:
        all_keys.update(item.keys())
    extras = sorted(all_keys - set(fieldnames))
    fieldnames.extend(extras)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = {}
            for k, v in item.items():
                if isinstance(v, (dict, list)):
                    row[k] = json.dumps(v, cls=DecimalEncoder, ensure_ascii=False)
                elif isinstance(v, Decimal):
                    row[k] = int(v) if v == int(v) else float(v)
                else:
                    row[k] = v
            writer.writerow(row)
    log.info("CSV written to %s", path)


def main():
    parser = argparse.ArgumentParser(description="Download DynamoDB messages to JSON/CSV")
    parser.add_argument("--table", default=None, help="DynamoDB table name (overrides MESSAGES_TABLE env var)")
    parser.add_argument("--region", default=None, help="AWS region (overrides AWS_REGION env var, default: us-east-1)")
    parser.add_argument("--output-dir", default=_script_dir, help="Directory to write output files (default: scripts/)")
    args = parser.parse_args()

    table_name = args.table or os.getenv("MESSAGES_TABLE")
    region = args.region or os.getenv("AWS_REGION", "us-east-1")

    if not table_name:
        log.error("No table name provided. Use --table or set MESSAGES_TABLE in .env")
        sys.exit(1)

    log.info("Downloading from DynamoDB table '%s' in %s ...", table_name, region)
    items = scan_table(table_name, region)

    if not items:
        log.info("Table is empty. Nothing to export.")
        return

    json_path = os.path.join(args.output_dir, f"dynamo_{table_name}.json")
    csv_path = os.path.join(args.output_dir, f"dynamo_{table_name}.csv")

    write_json(items, json_path)
    write_csv(items, csv_path)

    log.info("Done. %d items exported.", len(items))


if __name__ == "__main__":
    main()
