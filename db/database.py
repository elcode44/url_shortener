import os
import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional
from app.models import URLRecord

load_dotenv()

class Database:
    def __init__(self):
        self.conn = self._connect_with_retry()
        self.conn.autocommit = True
        self._create_table()

    def _connect_with_retry(self, retries=5, delay=2):
        for attempt in range(retries):
            try:
                return psycopg2.connect(os.getenv("DATABASE_URL"))
            except psycopg2.OperationalError as e:
                print(f"DB connection failed (attempt {attempt + 1}/{retries}), retrying in {delay}s...")
                time.sleep(delay)
        raise Exception("Could not connect to database after retries")

    def _create_table(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                    short_code  VARCHAR(10)  PRIMARY KEY,
                    long_url    TEXT         NOT NULL,
                    created_at  TIMESTAMP    DEFAULT NOW(),
                    hit_count   INTEGER      DEFAULT 0,
                    expires_at  TIMESTAMP    NULL
                );
            """)

    def save_url(self, short_code: str, long_url: str) -> URLRecord:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO urls (short_code, long_url)
                VALUES (%s, %s)
                ON CONFLICT (short_code) DO NOTHING
                RETURNING *;
            """, (short_code, long_url))
            row = cur.fetchone()
            if row:
                return URLRecord(**row)
            existing = self.find_url(short_code)
            if existing:
                return existing
            raise RuntimeError(f"Failed to save URL for short code '{short_code}'")

    def find_url(self, short_code: str) -> Optional[URLRecord]:
        """Look up a URL without incrementing hit count."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM urls WHERE short_code = %s;",
                (short_code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if row["expires_at"] and row["expires_at"] < datetime.utcnow():
                return None
            return URLRecord(**row)

    def get_url(self, short_code: str) -> Optional[URLRecord]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE urls
                SET hit_count = hit_count + 1
                WHERE short_code = %s
                RETURNING *;
            """, (short_code,))
            row = cur.fetchone()
            if not row:
                return None
            if row["expires_at"] and row["expires_at"] < datetime.utcnow():
                return None
            return URLRecord(**row)

    def get_all(self) -> list[URLRecord]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM urls ORDER BY created_at DESC;")
            return [URLRecord(**row) for row in cur.fetchall()]

    def delete_url(self, short_code: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM urls WHERE short_code = %s;", (short_code,))
            return cur.rowcount > 0

    def close(self):
        self.conn.close()