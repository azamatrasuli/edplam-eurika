"""One-shot schema migration — runs SQL files against DATABASE_URL, then exits."""
import os
import psycopg


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("MIGRATE: DATABASE_URL not set, skipping")
        return

    sql_dir = os.path.join(os.path.dirname(__file__), "sql")
    schema_file = os.path.join(sql_dir, "000_staging_schema.sql")
    if not os.path.exists(schema_file):
        schema_file = os.path.join(sql_dir, "000_full_schema.sql")
    if not os.path.exists(schema_file):
        print("MIGRATE: no schema file found, skipping")
        return

    print(f"MIGRATE: applying {os.path.basename(schema_file)}...")
    with psycopg.connect(url) as conn:
        with open(schema_file) as f:
            sql = f.read()
        conn.execute(sql)
        conn.commit()
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ).fetchall()
        print(f"MIGRATE: done — {len(rows)} tables")


if __name__ == "__main__":
    main()
