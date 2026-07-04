"""
Tests for app/shortener.py and app/id_allocator.py.

These use lightweight in-memory fakes for the database and cache instead
of real PostgreSQL/Redis connections, so the suite runs fast and doesn't
require the full Docker stack to be up.
"""
import pytest

from app.id_allocator import encode_base62, RangeAllocator
import app.shortener as shortener_module
from app.shortener import shorten, lookup, init_allocator


# ── Fakes ───────────────────────────────────────────────────────────

class FakeDatabase:
    """
    Stands in for db/database.py's Database class. Backs the ID counter
    and URL storage with plain Python dicts instead of real Postgres.
    """

    def __init__(self):
        self._counter = 0
        self._urls = {}  # short_code -> long_url

    def reserve_id_block(self, block_size: int) -> int:
        start = self._counter + 1
        self._counter += block_size
        return start

    def save_url(self, short_code: str, long_url: str):
        self._urls[short_code] = long_url

    def find_url(self, short_code: str):
        long_url = self._urls.get(short_code)
        if long_url is None:
            return None

        class _Record:
            pass

        record = _Record()
        record.long_url = long_url
        return record


class FakeCache:
    """In-memory stand-in for Redis, used to patch app.cache's module-level functions."""

    def __init__(self):
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value):
        self._store[key] = value


@pytest.fixture
def fake_cache(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(shortener_module, "get_from_cache", cache.get)
    monkeypatch.setattr(shortener_module, "set_in_cache", lambda k, v, ttl=3600: cache.set(k, v))
    return cache


@pytest.fixture
def fake_db():
    return FakeDatabase()


@pytest.fixture(autouse=True)
def reset_allocator():
    """Ensure each test starts with a clean global allocator state."""
    shortener_module._allocator = None
    yield
    shortener_module._allocator = None


# ── Base62 encoding ─────────────────────────────────────────────────

def test_encode_base62_zero():
    assert encode_base62(0) == "0"


def test_encode_base62_small_numbers_are_unique():
    codes = {encode_base62(i) for i in range(1000)}
    assert len(codes) == 1000  # no collisions among the first 1000 IDs


def test_encode_base62_is_deterministic():
    assert encode_base62(12345) == encode_base62(12345)


def test_encode_base62_only_uses_alphabet_characters():
    import string
    allowed = set(string.digits + string.ascii_lowercase + string.ascii_uppercase)
    code = encode_base62(999999)
    assert set(code).issubset(allowed)


# ── RangeAllocator ──────────────────────────────────────────────────

def test_allocator_returns_unique_ids_within_one_block(fake_db):
    allocator = RangeAllocator(fake_db, block_size=10)
    ids = [allocator.next_id() for _ in range(10)]
    assert len(set(ids)) == 10  # all unique
    assert ids == sorted(ids)   # sequential within a block


def test_allocator_requests_new_block_when_exhausted(fake_db):
    allocator = RangeAllocator(fake_db, block_size=5)
    ids = [allocator.next_id() for _ in range(12)]  # spans 3 blocks
    assert len(set(ids)) == 12  # still all unique across block boundaries


def test_multiple_allocators_never_collide(fake_db):
    """
    Simulates multiple app replicas, each with their own RangeAllocator,
    sharing one underlying database counter. This is the core guarantee
    Step 1 was built to provide.
    """
    allocator_a = RangeAllocator(fake_db, block_size=5)
    allocator_b = RangeAllocator(fake_db, block_size=5)
    allocator_c = RangeAllocator(fake_db, block_size=5)

    ids_a = [allocator_a.next_id() for _ in range(7)]
    ids_b = [allocator_b.next_id() for _ in range(7)]
    ids_c = [allocator_c.next_id() for _ in range(7)]

    all_ids = ids_a + ids_b + ids_c
    assert len(all_ids) == len(set(all_ids))  # zero collisions across replicas


def test_next_short_code_returns_base62_string(fake_db):
    allocator = RangeAllocator(fake_db, block_size=10)
    code = allocator.next_short_code()
    assert isinstance(code, str)
    assert len(code) > 0


# ── shorten() / lookup() ────────────────────────────────────────────

def test_shorten_without_init_raises(fake_db):
    with pytest.raises(RuntimeError):
        shorten("https://example.com", fake_db)


def test_shorten_returns_a_short_code(fake_db, fake_cache):
    init_allocator(fake_db, block_size=10)
    code = shorten("https://example.com", fake_db)
    assert isinstance(code, str)
    assert len(code) > 0


def test_shorten_same_url_twice_returns_different_codes(fake_db, fake_cache):
    """
    This is a deliberate behavior change from the old MD5-hash approach:
    the counter-based allocator is not idempotent by design, since that's
    what lets it avoid collision handling entirely.
    """
    init_allocator(fake_db, block_size=10)
    code1 = shorten("https://example.com", fake_db)
    code2 = shorten("https://example.com", fake_db)
    assert code1 != code2


def test_shorten_saves_to_database(fake_db, fake_cache):
    init_allocator(fake_db, block_size=10)
    code = shorten("https://example.com", fake_db)
    assert fake_db.find_url(code).long_url == "https://example.com"


def test_lookup_returns_saved_url(fake_db, fake_cache):
    init_allocator(fake_db, block_size=10)
    code = shorten("https://example.com/page", fake_db)
    assert lookup(code, fake_db) == "https://example.com/page"


def test_lookup_missing_code_returns_none(fake_db, fake_cache):
    init_allocator(fake_db, block_size=10)
    assert lookup("does-not-exist", fake_db) is None


def test_lookup_uses_cache_before_database(fake_db, fake_cache):
    init_allocator(fake_db, block_size=10)
    code = shorten("https://example.com", fake_db)

    # Remove from the "database" directly to prove the cache is what
    # actually serves the second lookup, not a fresh DB read.
    fake_db._urls[code] = "TAMPERED-VALUE-SHOULD-NOT-BE-RETURNED"
    fake_cache.set(code, "https://example.com")

    assert lookup(code, fake_db) == "https://example.com"