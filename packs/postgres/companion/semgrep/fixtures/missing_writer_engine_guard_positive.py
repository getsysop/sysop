# ruleid: missing-writer-engine-guard
def save_record(data):
    with writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ruleid: missing-writer-engine-guard — attribute form
def save_record_attr(data):
    with db.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ruleid: missing-writer-engine-guard — attribute form, bare call
def open_writer(data):
    conn = db.writer_engine.connect()
    return conn

# ruleid: missing-writer-engine-guard — guarded on a different instance
def save_record_other(data):
    if not other.writer_engine:
        return None
    with db.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ruleid: missing-writer-engine-guard — another instance name, nested reference
def save_nested(self, data):
    with self.db_config.writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ruleid: missing-writer-engine-guard — bare call, guarded on a different instance
def open_writer_other(data):
    if not other.writer_engine:
        return None
    return db.writer_engine.connect()

# ruleid: missing-writer-engine-guard — bare call, another instance name
def open_config_writer(self):
    return self.db_config.writer_engine.connect()

# ── Every call shape, unguarded ─────────────────────────────────────────────

# ruleid: missing-writer-engine-guard — "with" and no "as", attribute form
def with_no_as_attr(data):
    with db.writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — "with" and no "as", bare form
def with_no_as_bare(data):
    with writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — "async with ... as", attribute form
async def async_with_attr(data):
    async with db.writer_engine.begin() as conn:
        await conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ruleid: missing-writer-engine-guard — "async with ... as", bare form
async def async_with_bare(data):
    async with writer_engine.connect() as conn:
        await conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ruleid: missing-writer-engine-guard — "async with" and no "as"
async def async_with_no_as(data):
    async with db.writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — awaited call in an async def
async def awaited(data):
    conn = await db.writer_engine.connect()
    return conn

# ruleid: missing-writer-engine-guard — bare reference, bare call
def bare_call(data):
    return writer_engine.connect()

# ruleid: missing-writer-engine-guard — "with ... as", bare form, in a method
class Repo:
    def save(self, data):
        with self.writer_engine.begin() as conn:
            conn.execute("INSERT INTO t VALUES (:v)", {"v": data})

# ── Tests that name the engine and guard nothing ────────────────────────────
# A deep-expression guard (`if <... $REF ...>:`) would accept each of these.

# ruleid: missing-writer-engine-guard — a comparison on the engine is not a null check
def dialect_check(data):
    if db.writer_engine.dialect.name == "sqlite":
        return None
    with db.writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — an attribute of the engine is not the engine
def url_check(data):
    if not writer_engine.url:
        return None
    with writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — "and" skips the guard when the first test is false
def and_compound(data):
    if not data and not db.writer_engine:
        return None
    with db.writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — an "or" that guards another instance
def or_other_instance(data):
    if not db or not other.writer_engine:
        return None
    with db.writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — getattr on another instance
def getattr_other_instance(data):
    if not getattr(other, "writer_engine", None):
        return None
    return db.writer_engine.connect()

# ruleid: missing-writer-engine-guard — guarded on the attribute, called bare
def attr_guard_bare_call(data):
    if not db.writer_engine:
        return None
    return writer_engine.connect()

# ruleid: missing-writer-engine-guard — guarded bare, called on the attribute
def bare_guard_attr_call(data):
    if not writer_engine:
        return None
    return db.writer_engine.connect()

# ── Where the guard is ──────────────────────────────────────────────────────

# ruleid: missing-writer-engine-guard — the guard comes after the call
def guard_after(data):
    conn = db.writer_engine.connect()
    if not db.writer_engine:
        return None
    return conn

# ruleid: missing-writer-engine-guard — the guard only skips one loop iteration
def guard_in_loop(rows):
    for row in rows:
        if not db.writer_engine:
            continue
    with db.writer_engine.begin():
        pass

# ruleid: missing-writer-engine-guard — a module-level guard does not excuse a function
if not writer_engine:
    raise SystemExit("writer engine not available")


def after_module_guard(data):
    with writer_engine.begin():
        pass


# ruleid: missing-writer-engine-guard — the same, for the attribute form
if not db.writer_engine:
    raise SystemExit("writer engine not available")


def after_module_guard_attr(data):
    return db.writer_engine.connect()


# ruleid: missing-writer-engine-guard — a guard inside try is not at function entry
def guard_in_try(db):
    try:
        if not db.writer_engine:
            return None
    except Exception:
        return None
    return db.writer_engine.connect()


# ruleid: missing-writer-engine-guard — a guard inside with is not at function entry
def guard_in_with(lock):
    with lock:
        if writer_engine is None:
            return None
    writer_engine.begin()


# ruleid: missing-writer-engine-guard — an elif guard on another instance
def elif_other_instance(payload):
    if not payload:
        return 400
    elif not other.writer_engine:
        return 503
    return db.writer_engine.connect()


# ruleid: missing-writer-engine-guard — an elif "and" guards nothing
def elif_and(payload, a):
    if not payload:
        return 400
    elif not a and not writer_engine:
        return 503
    writer_engine.begin()


# ruleid: missing-writer-engine-guard — a guard in a fourth branch is past what the rule reads
def elif_fourth(payload, user, role):
    if not payload:
        return 400
    elif not user:
        return 401
    elif not role:
        return 403
    elif not writer_engine:
        return 503
    writer_engine.begin()
