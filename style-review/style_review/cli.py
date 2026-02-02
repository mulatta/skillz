"""Command-line interface for style-review."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .collector import collect_pr
from .config import get_data_dir, get_db_path
from .db import (
    SCHEMA,
    add_participant,
    get_db,
    get_or_create_repo,
    get_pr_id,
    pr_exists,
)
from .github import list_authored_prs, list_reviewed_prs
from .migrate import (
    MigrationState,
    migrate_directory,
    migrate_prs_directory,
)


def cmd_collect(args: argparse.Namespace) -> int:
    """Handle collect subcommand."""
    base_dir = get_data_dir(args.output)
    conn = get_db(base_dir)
    exclude_bots = not args.include_bots

    if args.author and args.reviewer:
        print("Error: Cannot specify both --author and --reviewer", file=sys.stderr)
        return 1

    if args.pr_number is not None:
        return _collect_single_pr(args, base_dir, conn, exclude_bots)

    if args.author:
        return _collect_by_author(args, base_dir, conn, exclude_bots)

    if args.reviewer:
        return _collect_by_reviewer(args, base_dir, conn, exclude_bots)

    print("Error: Must specify PR number or --author/--reviewer", file=sys.stderr)
    conn.close()
    return 1


def _collect_single_pr(
    args: argparse.Namespace,
    base_dir: Path,
    conn: sqlite3.Connection,
    exclude_bots: bool,
) -> int:
    """Collect a single PR."""
    if args.author or args.reviewer:
        print(
            "Error: Cannot specify PR number with --author or --reviewer",
            file=sys.stderr,
        )
        return 1
    success = collect_pr(
        args.repo, args.pr_number, base_dir, conn, exclude_bots=exclude_bots
    )
    conn.close()
    return 0 if success else 1


def _collect_by_author(
    args: argparse.Namespace,
    base_dir: Path,
    conn: sqlite3.Connection,
    exclude_bots: bool,
) -> int:
    """Collect PRs by author."""
    pr_numbers = list_authored_prs(
        args.repo, args.author, args.limit, args.state, args.since
    )
    if not pr_numbers:
        print(f"No PRs found by author {args.author} in {args.repo}", file=sys.stderr)
        conn.close()
        return 1

    print(f"Found {len(pr_numbers)} PRs by {args.author}", file=sys.stderr)
    success_count = 0
    skipped_count = 0
    repo_id = get_or_create_repo(conn, args.repo)

    for pr_num in pr_numbers:
        if args.skip_existing and pr_exists(conn, repo_id, pr_num):
            skipped_count += 1
            continue
        if collect_pr(
            args.repo, pr_num, base_dir, conn, "authored", args.author, exclude_bots
        ):
            success_count += 1

    print(
        f"Collected {success_count}/{len(pr_numbers)} PRs "
        f"(skipped {skipped_count} existing)",
        file=sys.stderr,
    )
    conn.close()
    return 0 if success_count > 0 or skipped_count > 0 else 1


def _collect_by_reviewer(
    args: argparse.Namespace,
    base_dir: Path,
    conn: sqlite3.Connection,
    exclude_bots: bool,
) -> int:
    """Collect PRs by reviewer."""
    pr_numbers = list_reviewed_prs(
        args.repo, args.reviewer, args.limit, args.state, args.since
    )
    if not pr_numbers:
        print(f"No PRs reviewed by {args.reviewer} in {args.repo}", file=sys.stderr)
        conn.close()
        return 1

    print(f"Found {len(pr_numbers)} PRs reviewed by {args.reviewer}", file=sys.stderr)
    success_count = 0
    skipped_count = 0
    repo_id = get_or_create_repo(conn, args.repo)

    for pr_num in pr_numbers:
        if args.skip_existing and pr_exists(conn, repo_id, pr_num):
            pr_id = get_pr_id(conn, repo_id, pr_num)
            if pr_id:
                add_participant(conn, pr_id, args.reviewer, "reviewer")
                conn.commit()
            skipped_count += 1
            continue
        if collect_pr(
            args.repo, pr_num, base_dir, conn, "reviewed", args.reviewer, exclude_bots
        ):
            success_count += 1

    print(
        f"Collected {success_count}/{len(pr_numbers)} PRs "
        f"(skipped {skipped_count} existing)",
        file=sys.stderr,
    )
    conn.close()
    return 0 if success_count > 0 or skipped_count > 0 else 1


def _format_json(rows: list[sqlite3.Row], columns: list[str]) -> str:
    """Format rows as JSON."""
    data = [
        {col: (row[col] if row[col] is not None else None) for col in columns}
        for row in rows
    ]
    return json.dumps(data, indent=2)


def _format_csv(rows: list[sqlite3.Row], columns: list[str]) -> str:
    """Format rows as CSV."""
    lines = [",".join(f'"{col}"' for col in columns)]
    for row in rows:
        vals = []
        for col in columns:
            val = row[col]
            if val is None:
                vals.append("")
            elif isinstance(val, str) and ("," in val or '"' in val):
                vals.append(f'"{val.replace(chr(34), chr(34) + chr(34))}"')
            else:
                vals.append(str(val))
        lines.append(",".join(vals))
    return "\n".join(lines)


def _format_table(rows: list[sqlite3.Row], columns: list[str]) -> str:
    """Format rows as ASCII table."""
    widths = [len(col) for col in columns]
    for row in rows:
        for i, col in enumerate(columns):
            val = str(row[col]) if row[col] is not None else ""
            widths[i] = max(widths[i], len(val))

    header = " | ".join(col.ljust(widths[i]) for i, col in enumerate(columns))
    separator = "-+-".join("-" * w for w in widths)

    lines = [header, separator]
    for row in rows:
        line = " | ".join(
            (str(row[col]) if row[col] is not None else "").ljust(widths[i])
            for i, col in enumerate(columns)
        )
        lines.append(line)
    return "\n".join(lines)


def _format_tsv(rows: list[sqlite3.Row], columns: list[str]) -> str:
    """Format rows as TSV."""
    lines = ["\t".join(columns)]
    lines.extend(
        "\t".join(str(row[col]) if row[col] is not None else "" for col in columns)
        for row in rows
    )
    return "\n".join(lines)


def format_rows(rows: list[sqlite3.Row], columns: list[str], fmt: str) -> str:
    """Format query results in specified format."""
    formatters = {
        "json": _format_json,
        "csv": _format_csv,
        "table": _format_table,
        "tsv": _format_tsv,
    }
    return formatters.get(fmt, _format_tsv)(rows, columns)


def cmd_query(args: argparse.Namespace) -> int:
    """Handle query subcommand - execute SQL query."""
    base_dir = get_data_dir(args.output)
    db_path = get_db_path(base_dir)

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute(args.sql)
        rows = cursor.fetchall()

        if not rows:
            print("No results", file=sys.stderr)
            return 0

        columns = [desc[0] for desc in cursor.description]
        print(format_rows(rows, columns, args.format))

    except sqlite3.Error as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


def cmd_db_schema(args: argparse.Namespace) -> int:
    """Show database schema."""
    print(SCHEMA)
    return 0


def cmd_db_migrate(args: argparse.Namespace) -> int:
    """Migrate existing data from old structure to new structure."""
    base_dir = get_data_dir(args.output)
    conn = get_db(base_dir)
    state = MigrationState()

    migrate_directory(conn, base_dir, base_dir / "authored", "authored", state)
    migrate_directory(conn, base_dir, base_dir / "reviewed", "reviewed", state)
    migrate_prs_directory(conn, base_dir, base_dir / "prs", state)

    conn.close()

    print("\nMigration complete:", file=sys.stderr)
    print(f"  Migrated: {state.migrated}", file=sys.stderr)
    print(f"  Merged duplicates: {state.skipped}", file=sys.stderr)
    print(f"  Errors: {state.errors}", file=sys.stderr)

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Collect GitHub PR data for style analysis and code review",
    )
    parser.add_argument(
        "--output", "-o", help="Data directory (default: ~/.local/share/style-review)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # collect subcommand
    collect_parser = subparsers.add_parser(
        "collect", help="Collect PR code and metadata"
    )
    collect_parser.add_argument("repo", help="Repository (owner/repo)")
    collect_parser.add_argument("pr_number", type=int, nargs="?", default=None)
    collect_parser.add_argument("--author", help="Collect PRs authored by user")
    collect_parser.add_argument("--reviewer", help="Collect PRs reviewed by user")
    collect_parser.add_argument("--limit", type=int, default=50)
    collect_parser.add_argument(
        "--state", choices=["all", "open", "closed", "merged"], default="merged"
    )
    collect_parser.add_argument(
        "--since", help="Date filter (2024-01-01 or 1y, 6m, 30d)"
    )
    collect_parser.add_argument("--skip-existing", action="store_true")
    collect_parser.add_argument("--exclude-bots", action="store_true", default=True)
    collect_parser.add_argument("--include-bots", action="store_true")

    # query subcommand
    query_parser = subparsers.add_parser("query", help="Execute SQL query on database")
    query_parser.add_argument("sql", help="SQL query to execute")
    query_parser.add_argument(
        "--format",
        "-f",
        choices=["tsv", "json", "table", "csv"],
        default="tsv",
        help="Output format (default: tsv)",
    )

    # db subcommand
    db_parser = subparsers.add_parser("db", help="Database management")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_subparsers.add_parser("schema", help="Show database schema")
    db_subparsers.add_parser("migrate", help="Migrate existing data to new structure")

    args = parser.parse_args()

    if args.command == "collect":
        return cmd_collect(args)
    if args.command == "query":
        return cmd_query(args)
    if args.command == "db":
        if args.db_command == "schema":
            return cmd_db_schema(args)
        if args.db_command == "migrate":
            return cmd_db_migrate(args)

    return 1
