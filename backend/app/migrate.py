"""Apply backend/migrations/*.sql in filename order."""

from __future__ import annotations

from pathlib import Path

import psycopg

from app.config import load_settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def split_sql(script: str) -> list[str]:
    """Split a migration on semicolons that are not inside quotes or comments."""
    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_line = False
    index = 0
    while index < len(script):
        char = script[index]
        nxt = script[index + 1] if index + 1 < len(script) else ""
        if in_line:
            buf.append(char)
            if char == "\n":
                in_line = False
            index += 1
            continue
        if in_single:
            buf.append(char)
            if char == "'" and nxt == "'":
                buf.append(nxt)
                index += 2
                continue
            if char == "'":
                in_single = False
            index += 1
            continue
        if char == "-" and nxt == "-":
            in_line = True
            buf.append(char)
            index += 1
            continue
        if char == "'":
            in_single = True
            buf.append(char)
            index += 1
            continue
        if char == ";":
            statement = "".join(buf).strip()
            if _has_sql(statement):
                statements.append(statement)
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    tail = "".join(buf).strip()
    if _has_sql(tail):
        statements.append(tail)
    return statements


def _has_sql(statement: str) -> bool:
    for line in statement.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return True
    return False


def apply(database_url: str, directory: Path = MIGRATIONS) -> None:
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise SystemExit(f"No migrations in {directory}")
    try:
        connection = psycopg.connect(database_url)
    except psycopg.OperationalError as exc:
        message = str(exc).splitlines()[0]
        if "://" in message or "password" in message.lower():
            message = "connection failed"
        raise SystemExit(
            f"Could not connect to Postgres: {message}. Start it with: docker compose up -d"
        ) from None
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.commit()
        for path in files:
            name = path.name
            done = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE filename = %s",
                (name,),
            ).fetchone()
            if done:
                print(f"skip {name}")
                continue
            statements = split_sql(path.read_text(encoding="utf-8"))
            print(f"apply {name} ({len(statements)} statements)")
            with connection.transaction():
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (name,),
                )
    print("migrations up to date")


def main() -> None:
    settings = load_settings()
    apply(settings.database_url)


if __name__ == "__main__":
    main()
