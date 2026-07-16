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
