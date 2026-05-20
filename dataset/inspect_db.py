"""
inspect_db.py — sanity-check the Postgres connection and peek at the schema.

This is the "wiring check" you should run at the start of any DB session before
writing real queries. It answers three questions:

  1. Can I connect at all? (auth + network + SSL)
  2. What tables exist and what columns do they have?
  3. What does the data actually look like (a handful of sample rows)?

Run from dataset/ with the project's venv:

    .venv/bin/python inspect_db.py
"""

import os
import pathlib

import psycopg
from dotenv import load_dotenv

# load_dotenv reads dataset/.env into os.environ. It's idempotent and safe to
# call multiple times. We point it at an explicit path so the script works no
# matter what the caller's cwd is.
load_dotenv(pathlib.Path(__file__).parent / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]


def main() -> None:
    # `with psycopg.connect(...)` opens a single TCP connection to Postgres
    # and guarantees it gets closed at the end of the block — even if we
    # crash. Connections are a finite resource on the server side; leaking
    # them eventually exhausts the pool.
    with psycopg.connect(DATABASE_URL) as conn:
        print(f"connected to {conn.info.host}:{conn.info.port} "
              f"db={conn.info.dbname} user={conn.info.user}")
        print()

        # ─── 1. List user tables in the public schema ────────────────────
        # information_schema is a SQL-standard set of views describing the
        # database itself ("metadata about metadata"). Querying it is how
        # you introspect a DB you didn't design.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
                """
            )
            tables = [r[0] for r in cur.fetchall()]
            print("tables in schema 'public':", tables)
            print()

        # ─── 2. For each table we care about, print its columns ──────────
        for table in ("songs", "takes"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (table,),
                )
                rows = cur.fetchall()
            print(f"── {table} ──")
            for name, dtype, nullable, default in rows:
                null = "NULL" if nullable == "YES" else "NOT NULL"
                dflt = f" default={default}" if default else ""
                print(f"  {name:<16} {dtype:<24} {null}{dflt}")
            print()

        # ─── 3. Row counts ───────────────────────────────────────────────
        # COUNT(*) on small tables is free. On huge tables you'd use
        # pg_class.reltuples for an estimate instead.
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM songs;")
            (n_songs,) = cur.fetchone()
            cur.execute("SELECT count(*) FROM takes;")
            (n_takes,) = cur.fetchone()
            cur.execute(
                "SELECT status, count(*) FROM takes GROUP BY status ORDER BY status;"
            )
            by_status = cur.fetchall()
        print(f"rows: songs={n_songs}  takes={n_takes}")
        print(f"takes by status: {by_status}")
        print()

        # ─── 4. Sample rows from each table ──────────────────────────────
        # LIMIT keeps output bounded. ORDER BY makes it deterministic.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug, title, author FROM songs ORDER BY id LIMIT 5;"
            )
            print("── songs (first 5) ──")
            for row in cur:
                print(f"  {row}")
            print()

            cur.execute(
                """
                SELECT t.id, s.slug, t.style, t.duration_s, t.status, t.storage_key
                FROM takes t
                JOIN songs s ON s.id = t.song_id
                ORDER BY t.created_at DESC
                LIMIT 5;
                """
            )
            print("── takes (5 most recent, joined to songs) ──")
            for row in cur:
                print(f"  {row}")


if __name__ == "__main__":
    main()
