# ruleid: missing-writer-engine-guard
def save_record(data):
    with writer_engine.begin() as conn:
        conn.execute("INSERT INTO t VALUES (:v)", {"v": data})
