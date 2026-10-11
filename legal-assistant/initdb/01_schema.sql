-- Sistema de registro do pack Legal. Toda data e todo `id` vêm daqui; o modelo nunca cria nenhum.
-- O `source_ref` (ex.: deadline:17) é montado pelo código a partir do `id` da linha.

CREATE TABLE matters (
    id SERIAL PRIMARY KEY,
    case_number VARCHAR(30) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    responsible_user VARCHAR(32) NOT NULL
);

CREATE TABLE deadlines (
    id SERIAL PRIMARY KEY,
    matter_id INT NOT NULL REFERENCES matters(id),
    kind VARCHAR(64) NOT NULL,
    due_date DATE NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('open', 'done', 'cancelled'))
);

CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    matter_id INT NOT NULL REFERENCES matters(id),
    occurred_on DATE NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    matter_id INT NOT NULL REFERENCES matters(id),
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL
);
