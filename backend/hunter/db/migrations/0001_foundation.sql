CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    platform TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority >= 0),
    reliability INTEGER CHECK (reliability BETWEEN 0 AND 100),
    activity INTEGER CHECK (activity BETWEEN 0 AND 100),
    content_value INTEGER CHECK (content_value BETWEEN 0 AND 100),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    removed_at TEXT
);
CREATE UNIQUE INDEX sources_active_url ON sources(connector_id, url) WHERE removed_at IS NULL;

CREATE TABLE connector_status (
    connector_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('AVAILABLE', 'DEGRADED', 'BLOCKED', 'UNAVAILABLE')),
    checked_at TEXT NOT NULL,
    last_success_at TEXT,
    last_error TEXT
);

CREATE TABLE raw_items (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    source_url TEXT NOT NULL,
    external_id TEXT,
    title TEXT,
    creator TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    metrics_snapshot_at TEXT,
    metrics_json TEXT CHECK (metrics_json IS NULL OR json_valid(metrics_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL
);
CREATE INDEX raw_items_retention ON raw_items(created_at);
CREATE INDEX raw_items_source ON raw_items(source_id, fetched_at);

CREATE TABLE briefs (
    id TEXT PRIMARY KEY,
    raw_item_id TEXT REFERENCES raw_items(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'COLLECTED' CHECK (status IN (
        'COLLECTED', 'PREPROCESSED', 'PROCESSING', 'PENDING_CLAUDE_REVIEW',
        'APPROVED_BY_CLAUDE', 'REVISION_REQUIRED', 'REJECTED_BY_CLAUDE', 'REVIEW_FAILED'
    )),
    revision_count INTEGER NOT NULL DEFAULT 0 CHECK (revision_count BETWEEN 0 AND 2),
    content_json TEXT CHECK (content_json IS NULL OR json_valid(content_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX briefs_inbox ON briefs(status, updated_at DESC, id);
CREATE INDEX briefs_raw_item ON briefs(raw_item_id);
CREATE INDEX briefs_retention ON briefs(created_at);

CREATE TABLE fingerprints (
    kind TEXT NOT NULL,
    digest TEXT NOT NULL,
    raw_item_id TEXT REFERENCES raw_items(id) ON DELETE CASCADE,
    brief_id TEXT REFERENCES briefs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    CHECK (raw_item_id IS NOT NULL OR brief_id IS NOT NULL),
    PRIMARY KEY (kind, digest)
);
CREATE INDEX fingerprints_retention ON fingerprints(created_at);
CREATE INDEX fingerprints_raw_item ON fingerprints(raw_item_id);
CREATE INDEX fingerprints_brief ON fingerprints(brief_id);

CREATE TABLE brief_revisions (
    brief_id TEXT NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision BETWEEN 0 AND 2),
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (brief_id, revision)
);

CREATE TABLE review_decisions (
    id INTEGER PRIMARY KEY,
    brief_id TEXT NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    expected_revision INTEGER NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason, char(9,10,11,12,13,32))) > 0),
    resulting_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (brief_id, expected_revision),
    FOREIGN KEY (brief_id, expected_revision) REFERENCES brief_revisions(brief_id, revision)
        ON DELETE CASCADE,
    CHECK (
        (action = 'APPROVE' AND resulting_status = 'APPROVED_BY_CLAUDE')
        OR (action = 'REJECT' AND resulting_status = 'REJECTED_BY_CLAUDE')
        OR (action = 'REQUEST_REVISION' AND resulting_status = CASE expected_revision
            WHEN 2 THEN 'REVIEW_FAILED' ELSE 'REVISION_REQUIRED' END)
    )
);

CREATE TRIGGER briefs_start_collected
BEFORE INSERT ON briefs
WHEN NEW.status <> 'COLLECTED' OR NEW.revision_count <> 0
BEGIN
    SELECT RAISE(ABORT, 'A brief must start collected');
END;

CREATE TRIGGER approval_requires_decision
BEFORE UPDATE OF status ON briefs
WHEN NEW.status = 'APPROVED_BY_CLAUDE' AND OLD.status <> NEW.status
AND (
    OLD.status <> 'PENDING_CLAUDE_REVIEW'
    OR OLD.revision_count <> NEW.revision_count
    OR NOT EXISTS (
        SELECT 1 FROM review_decisions
        WHERE brief_id = NEW.id AND expected_revision = NEW.revision_count AND action = 'APPROVE'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Approval requires a matching Claude review decision');
END;

CREATE TABLE trend_clusters (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    viral_signals_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(viral_signals_json)),
    trend_status TEXT NOT NULL,
    representative_brief_id TEXT REFERENCES briefs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE trend_cluster_members (
    cluster_id TEXT NOT NULL REFERENCES trend_clusters(id) ON DELETE CASCADE,
    raw_item_id TEXT NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    trusted INTEGER NOT NULL DEFAULT 0 CHECK (trusted IN (0, 1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (cluster_id, raw_item_id)
);
CREATE INDEX cluster_members_item ON trend_cluster_members(raw_item_id);

CREATE TABLE series_groups (
    id TEXT PRIMARY KEY,
    original_title TEXT NOT NULL,
    title_vi TEXT,
    genre TEXT,
    plot_summary TEXT,
    creator_or_publisher TEXT,
    complete INTEGER CHECK (complete IN (0, 1)),
    usage_rights TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE series_episodes (
    series_id TEXT NOT NULL REFERENCES series_groups(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    episode_number INTEGER CHECK (episode_number >= 1),
    raw_item_id TEXT REFERENCES raw_items(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (series_id, url)
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    worker TEXT NOT NULL CHECK (worker IN ('claude', 'codex', 'gemini', 'local', 'collector')),
    queue TEXT NOT NULL CHECK (queue IN ('urgent', 'normal')),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'dead')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 4),
    available_at TEXT NOT NULL,
    lease_token TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)
    )
);
CREATE INDEX jobs_claim ON jobs(worker, status, queue, available_at, created_at);
CREATE INDEX jobs_lease ON jobs(status, lease_expires_at);

CREATE TABLE job_attempts (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    number INTEGER NOT NULL CHECK (number BETWEEN 1 AND 4),
    worker_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT CHECK (outcome IN ('succeeded', 'failed', 'expired')),
    error_code TEXT,
    PRIMARY KEY (job_id, number)
);
CREATE INDEX job_attempts_errors ON job_attempts(finished_at DESC) WHERE error_code IS NOT NULL;

CREATE TABLE handoffs (
    id TEXT PRIMARY KEY,
    brief_id TEXT NOT NULL UNIQUE REFERENCES briefs(id) ON DELETE CASCADE,
    dedup_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('SELECTED', 'SENT', 'SEND_FAILED', 'ACKNOWLEDGED')),
    external_id TEXT,
    last_error TEXT,
    dispatch_token TEXT,
    dispatch_expires_at TEXT,
    selected_at TEXT NOT NULL,
    sent_at TEXT,
    acknowledged_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((dispatch_token IS NULL) = (dispatch_expires_at IS NULL)),
    CHECK (status NOT IN ('SENT', 'ACKNOWLEDGED') OR (external_id IS NOT NULL AND sent_at IS NOT NULL)),
    CHECK (status <> 'ACKNOWLEDGED' OR acknowledged_at IS NOT NULL)
);

CREATE TRIGGER handoff_requires_approved_brief
BEFORE INSERT ON handoffs
WHEN NOT EXISTS (SELECT 1 FROM briefs WHERE id = NEW.brief_id AND status = 'APPROVED_BY_CLAUDE')
BEGIN
    SELECT RAISE(ABORT, 'Handoff requires an approved brief');
END;

CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    brief_id TEXT NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('good', 'irrelevant', 'duplicate', 'bad-source')),
    created_at TEXT NOT NULL
);
CREATE INDEX feedback_brief ON feedback(brief_id, id);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    entity TEXT NOT NULL CHECK (entity IN ('source', 'setting')),
    entity_key TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('create', 'update', 'adjust', 'undo')),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    before_json TEXT CHECK (before_json IS NULL OR json_valid(before_json)),
    after_json TEXT CHECK (after_json IS NULL OR json_valid(after_json)),
    undoes_id INTEGER UNIQUE REFERENCES audit_log(id),
    created_at TEXT NOT NULL
);
CREATE INDEX audit_entity ON audit_log(entity, entity_key, id DESC);

CREATE TABLE ai_status (
    name TEXT PRIMARY KEY CHECK (name IN ('claude', 'codex', 'gemini', 'local')),
    status TEXT NOT NULL CHECK (
        status IN ('OK', 'AUTH_LOST', 'QUOTA_EXHAUSTED', 'TIMEOUT', 'UNAVAILABLE', 'ERROR')
    ),
    available INTEGER NOT NULL CHECK (available IN (0, 1)),
    last_error TEXT,
    quota_exhausted INTEGER NOT NULL CHECK (quota_exhausted IN (0, 1)),
    checked_at TEXT NOT NULL
);
