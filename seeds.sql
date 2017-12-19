CREATE TABLE radios (
  rid INTEGER PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL
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

