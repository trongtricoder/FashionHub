"""Supabase giả trong bộ nhớ để test route mà không cần mạng.

Hỗ trợ đúng những lệnh mà code đang dùng: select, insert, update, delete, eq, in_, order, limit.
"""
from datetime import datetime, timezone
from types import SimpleNamespace


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.op, self.payload = "select", None
        self.filters, self._limit, self._order, self._range = [], None, None, None

    def select(self, *_): self.op = "select"; return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, col, val): self.filters.append(lambda r: r.get(col) == val); return self
    def in_(self, col, vals): self.filters.append(lambda r: r.get(col) in list(vals)); return self
    def gte(self, col, val): self.filters.append(lambda r: r.get(col) is not None and r.get(col) >= val); return self
    def lt(self, col, val): self.filters.append(lambda r: r.get(col) is not None and r.get(col) < val); return self
    def order(self, col, desc=False): self._order = (col, desc); return self
    def limit(self, n): self._limit = n; return self
    def range(self, start, end): self._range = (start, end); return self

    def _matched(self, rows):
        return [r for r in rows if all(f(r) for f in self.filters)]

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "select":
            out = self._matched(rows)
            if self._order:
                col, desc = self._order
                out = sorted(out, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
            if self._range:   # như PostgREST: lấy dòng start..end, nhưng tối đa 1000 dòng mỗi lần gọi
                out = out[self._range[0]: self._range[1] + 1]
            elif self._limit:
                out = out[: self._limit]
            else:             # Supabase mặc định cắt ở 1000 dòng: giả lập để test bắt được lỗi quên phân trang
                out = out[:1000]
            return Result([dict(r) for r in out])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for item in items:
                defaults = {k: (v() if callable(v) else v) for k, v in self.db.defaults.get(self.name, {}).items()}
                row = dict(defaults, **item)
                row.setdefault("id", self.db.next_id(self.name))
                rows.append(row)
                created.append(dict(row))
            return Result(created)
        if self.op == "update":
            out = self._matched(rows)
            for r in out:
                r.update(self.payload)
            return Result([dict(r) for r in out])
        doomed = self._matched(rows)  # delete
        self.db.tables[self.name] = [r for r in rows if r not in doomed]
        return Result([dict(r) for r in doomed])


class FakeBucket:
    def __init__(self, storage, bucket): self.storage, self.bucket = storage, bucket

    def upload(self, path, data, options=None):
        self.storage.files[(self.bucket, path)] = (data, options)

    def get_public_url(self, path):
        return f"https://storage.test/{self.bucket}/{path}?"


class FakeStorage:
    def __init__(self): self.files = {}
    def from_(self, bucket): return FakeBucket(self, bucket)


def _now(): return datetime.now(timezone.utc).isoformat()


class FakeDB:
    def __init__(self, tables, tokens):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.defaults = {
            "orders": {"status": "pending", "payment_status": "unpaid",
                       "created_at": "2026-10-28T03:00:00+00:00", "updated_at": "2026-10-28T03:00:00+00:00"},
            "products": {"is_active": True, "sold_count": 0, "risk_score": 0, "risk_reasons": []},
            "ai_block_logs": {"created_at": _now, "restored": False},
            "moderation_queue": {"created_at": _now, "status": "pending"},
        }
        self.storage = FakeStorage()
        self._ids = {}
        tokens = dict(tokens)

        def get_user(token):
            if token not in tokens:
                raise ValueError("token sai")
            return SimpleNamespace(user=SimpleNamespace(id=tokens[token]))

        self.passwords = {}      # uid -> mật khẩu đã đặt qua auth.admin
        self.deleted_users = []

        def update_user_by_id(uid, attributes):
            if uid == "u-fail":
                raise RuntimeError("Supabase lỗi")
            self.passwords[uid] = attributes.get("password")

        def delete_user(uid):
            self.deleted_users.append(uid)
            self.tables["profiles"] = [p for p in self.tables.get("profiles", []) if p["id"] != uid]

        self.auth = SimpleNamespace(
            get_user=get_user,
            admin=SimpleNamespace(update_user_by_id=update_user_by_id, delete_user=delete_user))

    def next_id(self, name):
        start = max([r.get("id", 0) for r in self.tables.get(name, []) if isinstance(r.get("id"), int)] or [0])
        self._ids[name] = max(self._ids.get(name, 0), start) + 1
        return self._ids[name]

    def table(self, name):
        return Query(self, name)