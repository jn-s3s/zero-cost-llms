"""Generate provisional coding tiers and audited local-provider evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.benchmark_rankings import generate_rankings
from lib.repo_root import REPO_ROOT


def main() -> int:
    """Refresh sources and publish provisional tiers, workload views and an audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option, default, help_text in (
        ("input", "data", "directory containing provider outputs"),
        ("output", "data", "directory for benchmark catalogue and audit"),
        (
            "sources",
            "benchmark_sources",
            "directory containing seed source snapshots",
        ),
        (
            "mappings",
            "config/benchmarks/benchmark_model_mappings.json",
            "documented checkpoint identity file",
        ),
        ("providers", "config/providers.json", "configured provider catalogue"),
        (
            "policy",
            "config/benchmarks/benchmark_tier_policy.json",
            "frozen public tier policy",
        ),
    ):
        parser.add_argument(
            f"--{option}",
            type=Path,
            default=REPO_ROOT / default,
            help=f"{help_text} (default: %(default)s)",
        )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip source refresh; read cached snapshots or seeds",
    )
    args = parser.parse_args()
    return generate_rankings(
        args.input,
        args.output,
        args.sources,
        args.mappings,
        args.providers,
        offline=args.offline,
        policy_path=args.policy,
    )


if __name__ == "__main__":
    sys.exit(main())
