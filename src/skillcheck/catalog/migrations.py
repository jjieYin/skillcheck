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
