import sqlalchemy

# ok: sql-fstring — parameterized
conn.execute(sqlalchemy.text("SELECT * FROM observations WHERE id = :id"), {"id": val})

# ok: sql-fstring — static string
conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM observations"))

# ok: sql-fstring — f-string but not conn.execute
query = f"SELECT {col} FROM t"


# ── Q-244 negative controls: none of these may match sql-fstring-multiline ──

def prose_not_sql(n):
    # An English sentence that merely starts with a DML-looking word.
    return f"""
        Deleted {n} rows from the cache.
    """


def plain_docstring():
    """
    SELECT this is a docstring, not an f-string — no f prefix.
    """
    return 1


def keyword_not_first_token(t):
    # `SELECT` is present but the line does not start with it.
    return f"""
        -- SELECT is mentioned in this comment
        VACUUM {t}
    """


def same_line_is_the_grep_check_s_job(t):
    # Already covered by the line-oriented `sql-fstring` grep check; this rule
    # deliberately does not double-report it.
    return f"SELECT * FROM {t}"
