import sqlalchemy

# ok: sql-fstring — parameterized
conn.execute(sqlalchemy.text("SELECT * FROM observations WHERE id = :id"), {"id": val})

# ok: sql-fstring — static string
conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM observations"))

# ok: sql-fstring — f-string but not conn.execute
query = f"SELECT {col} FROM t"
