import threading

BASE62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def encode_base62(num: int) -> str:
    if num == 0:
        return BASE62_ALPHABET[0]
    chars = []
    base = len(BASE62_ALPHABET)
    while num > 0:
        num, rem = divmod(num, base)
        chars.append(BASE62_ALPHABET[rem])
    return "".join(reversed(chars))


class RangeAllocator:
    """
    Hands out unique integer IDs without hitting the DB on every request.
    Each process reserves a block of `block_size` IDs from Postgres in one
    atomic UPDATE, then serves IDs out of that block locally until it runs
    out and reserves the next one. Multiple app replicas each get their
    own non-overlapping block, so they never collide -- no coordination
    between replicas required.
    """

    def __init__(self, db, block_size: int = 1000):
        self.db = db
        self.block_size = block_size
        self._lock = threading.Lock()
        self._current = 0
        self._upper_bound = 0  # exclusive

    def next_id(self) -> int:
        with self._lock:
            if self._current >= self._upper_bound:
                start = self.db.reserve_id_block(self.block_size)
                self._current = start
                self._upper_bound = start + self.block_size
            next_id = self._current
            self._current += 1
            return next_id

    def next_short_code(self) -> str:
        return encode_base62(self.next_id())