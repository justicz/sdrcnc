import sqlite3
from flask import g

DATABASE = 'sdrcnc.db'

# http://flask.pocoo.org/docs/0.12/patterns/sqlite3/
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

# http://flask.pocoo.org/docs/0.12/patterns/sqlite3/
def query_db(query, args=(), one=False, commit=True):
    db = get_db()
    cur = db.execute(query, args)
    rv = cur.fetchall()
    if commit:
        db.commit()
    cur.close()
    return (rv[0] if rv else None) if one else rv

