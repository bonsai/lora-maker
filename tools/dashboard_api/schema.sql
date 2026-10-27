-- Unified Asset Database Schema
-- Supports: Hokusai (static images), Shishi (video frames)

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── Projects ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,   -- 'hokusai', 'shishi'
    label       TEXT NOT NULL,          -- display name
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO projects (id, name, label, description) VALUES
    (1, 'hokusai', '葛飾北斎', 'Hokusai manga / ukiyo-e static images'),
    (2, 'shishi',  'ヤマザキシシ', 'Yamazaki Shishi animation video frames');

-- ── Videos (Shishi only; Hokusai has NULL video_id) ──────
CREATE TABLE IF NOT EXISTS videos (
    id                  INTEGER PRIMARY KEY,
    project_id          INTEGER REFERENCES projects(id) NOT NULL DEFAULT 2,
    video_id            TEXT NOT NULL UNIQUE,
    title               TEXT,
    source_url          TEXT,
    local_video_path    TEXT,
    duration_seconds    REAL,
    permission_status   TEXT DEFAULT 'unknown',
    rights_basis        TEXT,
    creator             TEXT,
    approved_at         TEXT,
    notes               TEXT,
    meta_json           TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, video_id)
);

CREATE INDEX IF NOT EXISTS idx_videos_project ON videos(project_id);
CREATE INDEX IF NOT EXISTS idx_videos_status  ON videos(permission_status);

-- ── Frames ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS frames (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER REFERENCES projects(id) NOT NULL,
    video_id        TEXT REFERENCES videos(video_id),  -- NULL for Hokusai
    filename        TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    caption_path    TEXT,
    caption_text    TEXT,
    index_num       INTEGER,
    width           INTEGER,
    height          INTEGER,
    file_size_bytes INTEGER,
    has_caption     BOOLEAN DEFAULT FALSE,
    meta_json       TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_frames_project ON frames(project_id);
CREATE INDEX IF NOT EXISTS idx_frames_video   ON frames(video_id);
CREATE INDEX IF NOT EXISTS idx_frames_caption ON frames(has_caption);

-- ── VLM Reviews ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vlm_reviews (
    id                      INTEGER PRIMARY KEY,
    frame_id                INTEGER REFERENCES frames(id) UNIQUE NOT NULL,
    model_name              TEXT,
    subject                 TEXT,
    category                TEXT,
    style_notes             TEXT,
    training_suitability    INTEGER CHECK(training_suitability BETWEEN 0 AND 10),
    notes                   TEXT,
    raw_response            TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vlm_frame      ON vlm_reviews(frame_id);
CREATE INDEX IF NOT EXISTS idx_vlm_category   ON vlm_reviews(category);
CREATE INDEX IF NOT EXISTS idx_vlm_suit       ON vlm_reviews(training_suitability);

-- ── VLM Scores (loose axis names for extensibility) ──────
CREATE TABLE IF NOT EXISTS vlm_scores (
    review_id   INTEGER REFERENCES vlm_reviews(id) ON DELETE CASCADE,
    axis        TEXT NOT NULL,
    score       INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10),
    PRIMARY KEY (review_id, axis)
);

-- ── Analytics views ──────────────────────────────────────
CREATE VIEW IF NOT EXISTS v_frame_summary AS
SELECT
    f.project_id,
    p.label AS project_label,
    COUNT(*) AS total_frames,
    SUM(CASE WHEN f.has_caption THEN 1 ELSE 0 END) AS captioned_frames,
    COUNT(v.id) AS reviewed_frames,
    ROUND(AVG(v.training_suitability), 2) AS avg_suitability,
    MIN(v.training_suitability) AS min_suitability,
    MAX(v.training_suitability) AS max_suitability
FROM frames f
JOIN projects p ON f.project_id = p.id
LEFT JOIN vlm_reviews v ON f.id = v.frame_id
GROUP BY f.project_id;

CREATE VIEW IF NOT EXISTS v_score_distribution AS
SELECT
    f.project_id,
    p.label AS project_label,
    v.training_suitability,
    COUNT(*) AS count
FROM frames f
JOIN projects p ON f.project_id = p.id
JOIN vlm_reviews v ON f.id = v.frame_id
GROUP BY f.project_id, v.training_suitability;

CREATE VIEW IF NOT EXISTS v_category_distribution AS
SELECT
    f.project_id,
    p.label AS project_label,
    v.category,
    COUNT(*) AS count
FROM frames f
JOIN projects p ON f.project_id = p.id
JOIN vlm_reviews v ON f.id = v.frame_id
GROUP BY f.project_id, v.category;
