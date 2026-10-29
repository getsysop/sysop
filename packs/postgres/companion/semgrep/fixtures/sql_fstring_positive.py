import sqlalchemy

# ruleid: sql-fstring
conn.execute(f"SELECT * FROM {table_name}")

# ruleid: sql-fstring
conn.execute(sqlalchemy.text(f"INSERT INTO logs VALUES ('{val}')"))

# ruleid: sql-fstring
conn.execute(f"select * from observations where series_id = '{sid}'")


# ── Q-244: multi-line f-string SQL, invisible to the line-oriented grep check ──
# Both shapes below are taken from real production sites in the extraction
# source. They differ, and a rule written for only the first misses the second.

def bound_to_a_variable(token_where, raw_term):
    # Shape A: assigned to a name, executed later.
    # ruleid: sql-fstring-multiline
    meta_sql = f"""
        SELECT m.series_id, m.name
        FROM series_metadata m
        WHERE ({token_where})
    """
    return meta_sql


def returned_directly(extra_cols):
    # Shape B: returned directly, never bound to a name at all.
    # ruleid: sql-fstring-multiline
    return f"""
        SELECT series_id, observation_date, observation_value{extra_cols}
        FROM observations
    """


def lowercase_keyword(t):
    # ruleid: sql-fstring-multiline
    return f"""
        select * from {t}
    """


def single_quoted_triple(t):
    # ruleid: sql-fstring-multiline
    return f'''
        DELETE FROM {t}
    '''


def raw_f_prefix(t):
    # The `rf`/`fr` prefix arms had no case until the Phase 217 round showed
    # that narrowing the prefix group to plain `f` survived every test.
    # ruleid: sql-fstring-multiline
    return rf"""
        SELECT * FROM {t}
    """


def fr_prefix(t):
    # ruleid: sql-fstring-multiline
    return fr"""
        DELETE FROM {t}
    """
