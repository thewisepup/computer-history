from __future__ import annotations

import argparse
import json
import os
import sys

from computer_history.logs import log_files, read_records, resolve_log_dir, text_line


def cmd_logs(args: argparse.Namespace) -> int:
    log_dir = resolve_log_dir()
    if not log_files(log_dir):
        print(f"no log records yet in {log_dir}", file=sys.stderr)
        return 0
    records = read_records(
        log_dir, since=args.since, level=args.level, run=args.run, logger=args.logger
    )
    try:
        for doc in records:
            print(json.dumps(doc) if args.json else text_line(doc, with_run=True))
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0
