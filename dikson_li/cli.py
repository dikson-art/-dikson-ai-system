from __future__ import annotations

import argparse
import json

from .memory import JsonlMemoryStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dikson-li", description="Local project memory for Dikson-Li")
    subparsers = parser.add_subparsers(dest="command", required=True)

    remember = subparsers.add_parser("remember", help="Store a project memory record")
    remember.add_argument("project")
    remember.add_argument("content")
    remember.add_argument("--kind", default="note")

    recall = subparsers.add_parser("recall", help="Read recent project memory")
    recall.add_argument("project")
    recall.add_argument("--limit", type=int, default=20)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    store = JsonlMemoryStore()

    if args.command == "remember":
        record = store.append(project=args.project, kind=args.kind, content=args.content)
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        return 0

    records = store.list(args.project, limit=args.limit)
    print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
