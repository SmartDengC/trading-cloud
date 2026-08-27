CREATE TABLE memos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_username varchar(120) NOT NULL,
    text text NOT NULL DEFAULT '',
    source_type varchar(16) NOT NULL DEFAULT 'text',
    version integer NOT NULL DEFAULT 1,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX memos_owner_created_idx ON memos (owner_username, created_at DESC);

CREATE TABLE memo_attachments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    memo_id uuid NOT NULL REFERENCES memos(id) ON DELETE CASCADE,
    object_key text NOT NULL UNIQUE,
    file_name varchar(255) NOT NULL,
    content_type varchar(120) NOT NULL,
    size integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX memo_attachments_memo_idx ON memo_attachments (memo_id, created_at);
