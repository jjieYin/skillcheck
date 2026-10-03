V4_TO_V5_SQL = """
CREATE TABLE sync_groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    authority_skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    policy TEXT NOT NULL CHECK(policy = 'monitor_only'),
    baseline_revision TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE sync_group_members (
    group_id TEXT NOT NULL REFERENCES sync_groups(group_id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    role TEXT NOT NULL CHECK(role IN ('authority', 'mirror')),
    baseline_snapshot_id TEXT NOT NULL REFERENCES skill_snapshots(snapshot_id),
    baseline_content_hash TEXT NOT NULL,
    PRIMARY KEY(group_id, skill_id),
    UNIQUE(skill_id)
);

CREATE INDEX idx_sync_group_members_skill ON sync_group_members(skill_id);

UPDATE schema_meta SET value = '5' WHERE key = 'schema_version';
"""

V5_TO_V6_SQL = """
ALTER TABLE skill_snapshots ADD COLUMN instruction_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE skill_snapshots ADD COLUMN license TEXT NOT NULL DEFAULT '';
ALTER TABLE skill_snapshots ADD COLUMN compatibility TEXT NOT NULL DEFAULT '';
ALTER TABLE skill_snapshots ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE skill_snapshots ADD COLUMN allowed_tools_json TEXT NOT NULL DEFAULT '[]';

-- v5 did not retain a separate instruction identity.  This conservative
-- value is corrected by the next reconciliation pass.
UPDATE skill_snapshots SET instruction_hash = content_hash WHERE instruction_hash = '';
UPDATE schema_meta SET value = '6' WHERE key = 'schema_version';
"""

V6_TO_V7_SQL = """
ALTER TABLE skill_snapshots ADD COLUMN behavior_hash TEXT;
ALTER TABLE skill_snapshots ADD COLUMN execution_hash TEXT;
ALTER TABLE skill_snapshots ADD COLUMN hash_algorithm_revision TEXT;

CREATE TABLE segment_vectors (
    snapshot_id TEXT NOT NULL REFERENCES skill_snapshots(snapshot_id) ON DELETE CASCADE,
    model_signature TEXT NOT NULL,
    backend_kind TEXT NOT NULL,
    channel TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    dimensions INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, model_signature, channel, chunk_index)
);

CREATE INDEX idx_segment_vectors_model ON segment_vectors(model_signature, channel, snapshot_id);
UPDATE schema_meta SET value = '7' WHERE key = 'schema_version';
"""
