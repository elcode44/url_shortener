import os
import time
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional
from app.models import URLRecord

load_dotenv()


class Database:
    def __init__(self, minconn: int = 2, maxconn: int = 20):
        self.pool = self._connect_with_retry(minconn, maxconn)
        self._create_table()

    def _connect_with_retry(self, minconn, maxconn, retries=5, delay=2):
        for attempt in range(retries):
            try:
                pool = ThreadedConnectionPool(
                    minconn,
                    maxconn,
                    os.getenv("DATABASE_URL"),
                )
                # Verify the pool actually works before returning it
                conn = pool.getconn()
                pool.putconn(conn)
                return pool
            except psycopg2.OperationalError as e:
                print(f"DB connection failed (attempt {attempt + 1}/{retries}), retrying in {delay}s...")
                time.sleep(delay)
        raise Exception("Could not connect to database after retries")

    @contextmanager
    def _get_conn(self):
        """Borrow a connection from the pool, always return it -- even on error."""
        conn = self.pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)

    def _create_table(self):
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS urls (
                        short_code  VARCHAR(10)  PRIMARY KEY,
                        long_url    TEXT         NOT NULL,
                        created_at  TIMESTAMP    DEFAULT NOW(),
                        hit_count   INTEGER      DEFAULT 0,
                        expires_at  TIMESTAMP    NULL
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS id_counter (
                        id             INTEGER PRIMARY KEY DEFAULT 1,
                        current_value  BIGINT NOT NULL DEFAULT 0,
                        CHECK (id = 1)
                    );
                """)
                cur.execute("""
                    INSERT INTO id_counter (id, current_value)
                    VALUES (1, 0)
                    ON CONFLICT (id) DO NOTHING;
                """)

    def reserve_id_block(self, block_size: int) -> int:
        """Atomically reserve a block of IDs. Returns the starting ID (inclusive)."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    UPDATE id_counter
                    SET current_value = current_value + %s
                    WHERE id = 1
                    RETURNING current_value;
                """, (block_size,))
                new_value = cur.fetchone()["current_value"]
                return new_value - block_size + 1

    def save_url(self, short_code: str, long_url: str) -> URLRecord:
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO urls (short_code, long_url)
                    VALUES (%s, %s)
                    ON CONFLICT (short_code) DO NOTHING
                    RETURNING *;
                """, (short_code, long_url))
                row = cur.fetchone()
                if row:
                    return URLRecord(**row)

        # Fallback outside the transaction block: someone else beat us to
        # this short_code (shouldn't happen with the range allocator, but
        # kept for safety/back-compat).
        existing = self.find_url(short_code)
        if existing:
            return existing
        raise RuntimeError(f"Failed to save URL for short code '{short_code}'")

    def find_url(self, short_code: str) -> Optional[URLRecord]:
        """Look up a URL without incrementing hit count."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM urls ORDER BY created_at DESC;")
                return [URLRecord(**row) for row in cur.fetchall()]

    def delete_url(self, short_code: str) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM urls WHERE short_code = %s;", (short_code,))
                return cur.rowcount > 0

    def close(self):
        self.pool.closeall()