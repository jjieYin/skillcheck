CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO schema_meta(key, value) VALUES ('schema_version', '5');

CREATE TABLE library_roots (
    root_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    scope TEXT NOT NULL,
    project_path TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE skills (
    skill_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES library_roots(root_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL,
    current_snapshot_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(root_id, relative_path)
);

CREATE TABLE skill_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    root_id TEXT NOT NULL REFERENCES library_roots(root_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    tools_json TEXT NOT NULL DEFAULT '[]',
    permissions_json TEXT NOT NULL DEFAULT '[]',
    environments_json TEXT NOT NULL DEFAULT '[]',
    inputs_json TEXT NOT NULL DEFAULT '[]',
    outputs_json TEXT NOT NULL DEFAULT '[]',
    indexed_at TEXT NOT NULL,
    parse_error TEXT
);

CREATE TABLE sync_events (
    event_id TEXT PRIMARY KEY,
    revision TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    removed INTEGER NOT NULL DEFAULT 0,
    invalid INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE vectors (
    snapshot_id TEXT NOT NULL REFERENCES skill_snapshots(snapshot_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, model)
);

CREATE TABLE analysis_runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    revision TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE candidate_groups (
    group_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    score REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE group_members (
    group_id TEXT NOT NULL REFERENCES candidate_groups(group_id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES skill_snapshots(snapshot_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY(group_id, snapshot_id)
);

CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES candidate_groups(group_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE agent_reviews (
    review_id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES candidate_groups(group_id) ON DELETE CASCADE,
    agent TEXT NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES analysis_runs(run_id) ON DELETE SET NULL,
    format TEXT NOT NULL,
    path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE source_preflights (
    preflight_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE install_plans (
    plan_id TEXT PRIMARY KEY,
    source_preflight_id TEXT REFERENCES source_preflights(preflight_id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

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

CREATE INDEX idx_skills_root_path ON skills(root_id, relative_path);
CREATE INDEX idx_snapshots_skill ON skill_snapshots(skill_id, indexed_at DESC);
CREATE INDEX idx_group_members_snapshot ON group_members(snapshot_id);
CREATE INDEX idx_evidence_group ON evidence(group_id);
CREATE INDEX idx_sync_group_members_skill ON sync_group_members(skill_id);

CREATE VIRTUAL TABLE skill_fts USING fts5(
    snapshot_id UNINDEXED,
    name,
    description,
    body
);
