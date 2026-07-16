import sqlalchemy

# ruleid: sql-fstring
conn.execute(f"SELECT * FROM {table_name}")

# ruleid: sql-fstring
conn.execute(sqlalchemy.text(f"INSERT INTO logs VALUES ('{val}')"))

# ruleid: sql-fstring
conn.execute(f"select * from observations where series_id = '{sid}'")
