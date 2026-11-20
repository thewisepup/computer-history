from __future__ import annotations

import argparse
import dataclasses
import sys
import typing
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from computer_history.synthetic import (
    DATABASE_NAME,
    MANIFEST_NAME,
    PERSONAS,
    SCENARIOS,
    TIERS,
    BuildFailed,
    DatasetInputs,
    cache_root,
    live_folders,
    make_dev_database,
)

REGISTRIES: Mapping[str, Mapping[str, object]] = {
    "persona": PERSONAS,
    "scenario": SCENARIOS,
    "tier": TIERS,
}
PARSERS: Mapping[type, Callable[[str], Any]] = {
    str: str,
    int: int,
    float: float,
    date: date.fromisoformat,
}
LABELS = {DATABASE_NAME: "database", MANIFEST_NAME: "manifest"}


def add_dev_commands(dev: argparse.ArgumentParser) -> None:
    commands = dev.add_subparsers(dest="dev_command", required=True)
    help_text = (
        "Build (or reuse from the dataset cache) a synthetic dataset and copy its database,"
        " manifest and rendered sources into a folder. Never touches the live database."
    )
    build = commands.add_parser("build-db", help=help_text, description=help_text)
    hints = typing.get_type_hints(DatasetInputs)
    for field in dataclasses.fields(DatasetInputs):
        _add_input_option(build, field, hints[field.name])
    build.add_argument("--out", type=Path, required=True, help="folder to copy the dataset into")
    build.add_argument(
        "--force", action="store_true", help="replace dataset files already in the folder"
    )


def _add_input_option(
    parser: argparse.ArgumentParser, field: dataclasses.Field[Any], kind: object
) -> None:
    flag = "--" + field.name.replace("_", "-")
    required = field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    default = argparse.SUPPRESS if not required else None
    shown = "" if required else f" (default: {field.default})"
    if kind is bool:
        parser.add_argument(flag, dest=field.name, action="store_true", default=default)
        return
    if kind not in PARSERS:
        raise TypeError(f"dev build-db cannot parse DatasetInputs.{field.name} ({kind})")
    choices = REGISTRIES.get(field.name)
    parser.add_argument(
        flag,
        dest=field.name,
        type=PARSERS[kind],
        choices=None if choices is None else list(choices),
        required=required,
        default=default,
        help=f"dataset {field.name.replace('_', ' ')}{shown}",
    )


def cmd_dev(args: argparse.Namespace) -> int:
    return DEV_HANDLERS[args.dev_command](args)


def cmd_build_db(args: argparse.Namespace) -> int:
    names = [field.name for field in dataclasses.fields(DatasetInputs)]
    try:
        inputs = DatasetInputs(**{name: getattr(args, name) for name in names if name in args})
    except (ValueError, LookupError) as exc:
        print(f"dev build-db: invalid dataset inputs: {exc}", file=sys.stderr)
        return 2
    try:
        made = make_dev_database(
            inputs,
            args.out,
            cache=cache_root(),
            live=live_folders(args.db_path),
            force=args.force,
        )
    except (ValueError, OSError, BuildFailed) as exc:
        print(f"dev build-db refused: {exc}", file=sys.stderr)
        return 1
    described = ", ".join(f"{name}={value}" for name, value in dataclasses.asdict(inputs).items())
    how = "built" if made.dataset.built else "reused from the cache"
    print(f"Dataset {described}")
    print(f"  {how}: {made.dataset.folder}")
    for path in made.copied:
        label = LABELS.get(path.name, path.name + ("/" if path.is_dir() else ""))
        print(f"  {label:<10} {path}")
    return 0


DEV_HANDLERS: Mapping[str, Callable[[argparse.Namespace], int]] = {"build-db": cmd_build_db}
