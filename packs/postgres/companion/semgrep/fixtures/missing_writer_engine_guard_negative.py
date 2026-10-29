# ok: missing-writer-engine-guard
def save_record(data):
    if not writer_engine:
        return []
    with writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard
def save_record2(data):
    if not writer_engine:
        raise RuntimeError("writer_engine not available")
    with writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — connect() form
def save_record3(data):
    if not writer_engine:
        return None
    with writer_engine.connect() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — attribute form, the convention's own shape
def save_record_attr(data):
    if not db.writer_engine:
        return None
    with db.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — attribute form, bare call
def open_writer(data):
    if not db.writer_engine:
        return None
    conn = db.writer_engine.connect()
    return conn

# ok: missing-writer-engine-guard — another instance name
def save_db_config(data):
    if not db_config.writer_engine:
        return None
    with db_config.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — a reader engine is not this rule's subject
def read_rows():
    with db.reader_engine.connect() as conn:
        return conn.execute("SELECT 1").fetchall()

# ok: missing-writer-engine-guard — bare call, another instance name, guarded
def open_config_writer_guarded():
    if not db_config.writer_engine:
        return None
    return db_config.writer_engine.connect()

# ── Every guard form, one case each, across every call shape ────────────────
# At least one case per guard pattern in the rule, so deleting any one of
# them makes a case here fire. Every `if` line below is also a line the pack's
# wrong-engine check drops (tests/test_wrong_engine_check.py runs it over this
# file), so the two checks agree on what a guard is.

# ok: missing-writer-engine-guard — bare reference, `not` last in an "or"
def bare_not_last(data):
    if data is None or not writer_engine:
        return None
    with writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — bare reference, `not` first in an "or"
async def bare_not_first(data):
    if not writer_engine or data is None:
        return None
    async with writer_engine.begin() as conn:
        await conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — bare reference, `not` in the middle of an "or"
async def bare_not_middle(data):
    if data is None or not writer_engine or not data.rows:
        return None
    async with writer_engine.connect():
        pass

# ok: missing-writer-engine-guard — bare reference, `is None`, return
def bare_is_none(data):
    if writer_engine is None:
        return None
    return writer_engine.connect()

# ok: missing-writer-engine-guard — bare reference, `is None` last in an "or"
async def bare_is_none_last(data):
    if data is None or writer_engine is None:
        raise RuntimeError("writer engine not available")
    conn = await writer_engine.connect()
    return conn

# ok: missing-writer-engine-guard — bare reference, `is None` first in an "or"
def bare_is_none_first(data):
    if writer_engine is None or data is None:
        return None
    with writer_engine.connect() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — bare reference, `is None` in the middle
def bare_is_none_middle(data):
    if data is None or writer_engine is None or not data.rows:
        return None
    with writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — `not db or not db.writer_engine`
def attr_not_last(db, data):
    if not db or not db.writer_engine:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — attribute, `not` first in an "or"
async def attr_not_first(db, data):
    if not db.writer_engine or not db.reader_engine:
        return None
    async with db.writer_engine.begin() as conn:
        await conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — attribute, `not` in the middle of an "or"
def attr_not_middle(db, data):
    if not db or not db.writer_engine or not data:
        return None
    return db.writer_engine.connect()

# ok: missing-writer-engine-guard — attribute, `is None`, raise
def attr_is_none(data):
    if db.writer_engine is None:
        raise RuntimeError("writer engine not available")
    with db.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — attribute, `is None` last in an "or"
async def attr_is_none_last(data):
    if data is None or db.writer_engine is None:
        return None
    async with db.writer_engine.connect():
        pass

# ok: missing-writer-engine-guard — attribute, `is None` first in an "or"
def attr_is_none_first(self, data):
    if self.db.writer_engine is None or data is None:
        return None
    with self.db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — attribute, `is None` in the middle of an "or"
def attr_is_none_middle(data):
    if data is None or db.writer_engine is None or not data.rows:
        return None
    with db.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — getattr, no default
def getattr_not(data):
    if not getattr(db, "writer_engine"):
        return None
    return db.writer_engine.connect()

# ok: missing-writer-engine-guard — getattr, no default, last in an "or"
def getattr_not_last(data):
    if not db or not getattr(db, "writer_engine"):
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr, no default, first in an "or"
def getattr_not_first(data):
    if not getattr(db, "writer_engine") or not db:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr, no default, in the middle
def getattr_not_middle(data):
    if not db or not getattr(db, "writer_engine") or not data:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr with a None default
def getattr_none(data):
    if not getattr(db, "writer_engine", None):
        return None
    with db.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — getattr with a None default, last in an "or"
async def getattr_none_last(data):
    if data is None or not getattr(db, 'writer_engine', None):
        return None
    async with db.writer_engine.begin() as conn:
        await conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — getattr with a None default, first in an "or"
def getattr_none_first(data):
    if not getattr(db, "writer_engine", None) or data is None:
        return None
    return db.writer_engine.connect()

# ok: missing-writer-engine-guard — getattr with a None default, in the middle
def getattr_none_middle(data):
    if data is None or not getattr(db, "writer_engine", None) or not data.rows:
        return None
    with db.writer_engine.connect():
        pass

# ok: missing-writer-engine-guard — getattr, no default, `is None`
def getattr_is_none(data):
    if getattr(db, "writer_engine") is None:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr, no default, `is None` last in an "or"
def getattr_is_none_last(data):
    if data is None or getattr(db, "writer_engine") is None:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr, no default, `is None` first in an "or"
def getattr_is_none_first(data):
    if getattr(db, "writer_engine") is None or data is None:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr, no default, `is None` in the middle
def getattr_is_none_middle(data):
    if data is None or getattr(db, "writer_engine") is None or not data.rows:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr with a None default, `is None`
def getattr_none_is_none(data):
    if getattr(self.cfg, "writer_engine", None) is None:
        return []
    return self.cfg.writer_engine.connect()

# ok: missing-writer-engine-guard — getattr, None default, `is None` last in an "or"
def getattr_none_is_none_last(data):
    if data is None or getattr(db, "writer_engine", None) is None:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr, None default, `is None` first in an "or"
def getattr_none_is_none_first(data):
    if getattr(db, "writer_engine", None) is None or data is None:
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — getattr, None default, `is None` in the middle
def getattr_none_is_none_middle(data):
    if data is None or getattr(db, "writer_engine", None) is None or not data.rows:
        return None
    with db.writer_engine.begin():
        pass

# ── Shapes around the guard ─────────────────────────────────────────────────

# ok: missing-writer-engine-guard — parenthesized guard
def parenthesized(data):
    if (not db.writer_engine):
        return None
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — the call sits in the guard's else
def in_else(data):
    if not db.writer_engine:
        log_unavailable()
    else:
        with db.writer_engine.begin():
            pass

# ok: missing-writer-engine-guard — a method, guarded on self
class Repo:
    def save(self, data):
        if not self.writer_engine:
            return None
        with self.writer_engine.begin() as conn:
            conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ok: missing-writer-engine-guard — calls nested deeper than the guard
def nested_calls(rows):
    if not db.writer_engine:
        return 0
    for row in rows:
        with db.writer_engine.begin():
            pass
    return len(rows)

# ok: missing-writer-engine-guard — a call outside any function is not this rule's subject
ENGINE_AT_IMPORT = writer_engine.connect()

# ok: missing-writer-engine-guard — a guard as the second test of an entry if/elif chain
def elif_guard(payload):
    if not payload:
        return 400
    elif not writer_engine:
        return 503
    with writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (1)")

# ok: missing-writer-engine-guard — the same, attribute form, is None
def elif_guard_attr(payload):
    if not payload:
        return 400
    elif db.writer_engine is None:
        return 503
    return db.writer_engine.connect()

# ok: missing-writer-engine-guard — a guard as the third test, getattr form
def elif_third(payload, user):
    if not payload:
        return 400
    elif not user:
        return 401
    elif not getattr(db, "writer_engine", None):
        return 503
    with db.writer_engine.begin():
        pass

# ok: missing-writer-engine-guard — an elif guard in an or, with an else after it
def elif_or_else(payload):
    if not payload:
        return 400
    elif payload.dry_run or not db.writer_engine:
        return 503
    else:
        audit(payload)
    db.writer_engine.begin()

# ok: missing-writer-engine-guard — else: if <guard> is the same statement as elif <guard>
def else_if_guard(payload):
    if not payload:
        return 400
    else:
        if not writer_engine:
            return 503
    writer_engine.connect()
