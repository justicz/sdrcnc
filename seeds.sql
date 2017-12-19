CREATE TABLE radios (
  rid INTEGER PRIMARY KEY,
  api_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE,
  description TEXT
);

CREATE UNIQUE INDEX idx_radios_token ON radios (token);

CREATE TABLE commands (
  cid INTEGER PRIMARY KEY,
  completed INTEGER DEFAULT 0,
  command TEXT NOT NULL,
  result BLOB,
  rid INTEGER NOT NULL,
  FOREIGN KEY(rid) REFERENCES radios(rid)
);

