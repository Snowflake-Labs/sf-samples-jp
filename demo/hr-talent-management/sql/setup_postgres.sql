-- ============================================================================
-- Snowflake HR Intelligence — Snowflake Postgres セットアップ SQL
-- ============================================================================
-- 実行先: Snowflake Postgres インスタンス（psql / pgAdmin 等で接続）
-- ============================================================================

-- ============================================================================
-- 1. スキーマ
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS hr;
SET search_path TO hr, public;

-- ============================================================================
-- 2. マスタテーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.departments (
    dept_id        SERIAL        PRIMARY KEY,
    dept_name      VARCHAR(100)  NOT NULL,
    dept_code      VARCHAR(20)   NOT NULL UNIQUE,
    parent_dept_id INTEGER       REFERENCES hr.departments(dept_id),
    level          SMALLINT      NOT NULL DEFAULT 1,
    is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hr.positions (
    position_id     SERIAL        PRIMARY KEY,
    title           VARCHAR(100)  NOT NULL,
    dept_id         INTEGER       NOT NULL REFERENCES hr.departments(dept_id),
    grade           VARCHAR(10)   NOT NULL,
    -- E1=役員, D1=本部長, D2=部長, M1=次長, M2=課長, S1=課長補佐, S2=主査, J1=主任, J2=主事, J3=新卒
    required_skills JSONB,
    is_vacant       BOOLEAN       NOT NULL DEFAULT FALSE,
    headcount       SMALLINT      NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hr.skills (
    skill_id    SERIAL       PRIMARY KEY,
    skill_name  VARCHAR(100) NOT NULL UNIQUE,
    category    VARCHAR(50)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 3. 社員テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.employees (
    employee_id   SERIAL        PRIMARY KEY,
    employee_code VARCHAR(20)   NOT NULL UNIQUE,
    first_name    VARCHAR(50)   NOT NULL,
    last_name     VARCHAR(50)   NOT NULL,
    email         VARCHAR(255)  NOT NULL UNIQUE,
    phone         VARCHAR(20),
    hire_date     DATE          NOT NULL,
    birth_date    DATE,
    gender        VARCHAR(10),
    dept_id       INTEGER       NOT NULL REFERENCES hr.departments(dept_id),
    position_id   INTEGER       REFERENCES hr.positions(position_id),
    manager_id    INTEGER       REFERENCES hr.employees(employee_id),
    status        VARCHAR(20)   NOT NULL DEFAULT 'active',
    salary        INTEGER,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_emp_dept ON hr.employees(dept_id);
CREATE INDEX idx_emp_manager ON hr.employees(manager_id);
CREATE INDEX idx_emp_status ON hr.employees(status);

-- ============================================================================
-- 4. 評価テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.evaluations (
    evaluation_id SERIAL        PRIMARY KEY,
    employee_id   INTEGER       NOT NULL REFERENCES hr.employees(employee_id),
    evaluator_id  INTEGER       NOT NULL REFERENCES hr.employees(employee_id),
    period        VARCHAR(10)   NOT NULL,
    score         NUMERIC(3,1),
    grade         VARCHAR(5),
    comment       TEXT,
    self_comment  TEXT,
    status        VARCHAR(20)   NOT NULL DEFAULT 'draft',
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE(employee_id, period)
);

CREATE INDEX idx_eval_emp ON hr.evaluations(employee_id);
CREATE INDEX idx_eval_evaluator ON hr.evaluations(evaluator_id);
CREATE INDEX idx_eval_status ON hr.evaluations(status);

-- ============================================================================
-- 5. 1on1メモ
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.one_on_one_notes (
    note_id      SERIAL       PRIMARY KEY,
    employee_id  INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    manager_id   INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    note_date    DATE         NOT NULL,
    content      TEXT         NOT NULL,
    category     VARCHAR(30),
    is_private   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_note_emp ON hr.one_on_one_notes(employee_id);
CREATE INDEX idx_note_mgr ON hr.one_on_one_notes(manager_id);
CREATE INDEX idx_note_date ON hr.one_on_one_notes(note_date);

-- ============================================================================
-- 6. スキル紐付け
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.employee_skills (
    id           SERIAL       PRIMARY KEY,
    employee_id  INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    skill_id     INTEGER      NOT NULL REFERENCES hr.skills(skill_id),
    proficiency  SMALLINT     NOT NULL CHECK (proficiency BETWEEN 1 AND 5),
    certified_at DATE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE(employee_id, skill_id)
);

-- ============================================================================
-- 7. 異動申請
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.transfer_requests (
    request_id       SERIAL       PRIMARY KEY,
    employee_id      INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    from_dept_id     INTEGER      NOT NULL REFERENCES hr.departments(dept_id),
    to_dept_id       INTEGER      NOT NULL REFERENCES hr.departments(dept_id),
    from_position_id INTEGER      REFERENCES hr.positions(position_id),
    to_position_id   INTEGER      REFERENCES hr.positions(position_id),
    reason           TEXT,
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    requested_by     INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    approved_by      INTEGER      REFERENCES hr.employees(employee_id),
    requested_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ
);

CREATE INDEX idx_transfer_emp ON hr.transfer_requests(employee_id);
CREATE INDEX idx_transfer_status ON hr.transfer_requests(status);

-- ============================================================================
-- 8. アプリユーザー
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.app_users (
    user_id       SERIAL       PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'HR_VIEWER',
    employee_id   INTEGER      REFERENCES hr.employees(employee_id),
    dept_scope    INTEGER[],
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 9. 候補者リスト & アクション
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.candidate_lists (
    id           SERIAL       PRIMARY KEY,
    employee_id  INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    list_name    VARCHAR(100) NOT NULL,
    created_by   INTEGER      NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hr.action_items (
    action_id    SERIAL       PRIMARY KEY,
    employee_id  INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    action_type  VARCHAR(30)  NOT NULL,
    description  TEXT         NOT NULL,
    status       VARCHAR(20)  NOT NULL DEFAULT 'open',
    assigned_to  INTEGER,
    due_date     DATE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 10. updated_at 自動更新トリガー
-- ============================================================================

CREATE OR REPLACE FUNCTION hr.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_employees_updated_at
    BEFORE UPDATE ON hr.employees
    FOR EACH ROW EXECUTE FUNCTION hr.update_updated_at();

CREATE TRIGGER trg_evaluations_updated_at
    BEFORE UPDATE ON hr.evaluations
    FOR EACH ROW EXECUTE FUNCTION hr.update_updated_at();

CREATE TRIGGER trg_departments_updated_at
    BEFORE UPDATE ON hr.departments
    FOR EACH ROW EXECUTE FUNCTION hr.update_updated_at();

-- ============================================================================
-- 10b. 休暇取得テーブル（離職予測モデルの特徴量用）
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.leave_records (
    leave_id     SERIAL       PRIMARY KEY,
    employee_id  INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    leave_type   VARCHAR(30)  NOT NULL,
    start_date   DATE         NOT NULL,
    end_date     DATE         NOT NULL,
    days         NUMERIC(4,1) NOT NULL,
    status       VARCHAR(20)  NOT NULL DEFAULT 'approved',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_leave_emp ON hr.leave_records(employee_id);
CREATE INDEX idx_leave_date ON hr.leave_records(start_date);

COMMENT ON TABLE hr.leave_records IS '休暇取得履歴（有給・特別・病欠等）。離職予測モデルの特徴量として利用';

-- ============================================================================
-- 10c. シミュレーションセッション管理テーブル（アプリ生成データ → Postgres）
-- ============================================================================

CREATE TABLE IF NOT EXISTS hr.simulation_sessions (
    session_id     VARCHAR(36)  PRIMARY KEY,
    scenario_name  VARCHAR(200) NOT NULL,
    clone_db_name  VARCHAR(100) NOT NULL,
    created_by     INTEGER      NOT NULL REFERENCES hr.app_users(user_id),
    status         VARCHAR(20)  NOT NULL DEFAULT 'active',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    dropped_at     TIMESTAMPTZ
);

COMMENT ON TABLE hr.simulation_sessions IS 'Zero-copy Clone シミュレーションのメタ情報管理';

-- ============================================================================
-- 10e. ML Evidence 拡張テーブル（根拠説明用追加データ）
-- ============================================================================

-- 経歴・異動履歴（確定済みの全配属履歴）
CREATE TABLE IF NOT EXISTS hr.career_history (
    history_id       SERIAL        PRIMARY KEY,
    employee_id      INTEGER       NOT NULL REFERENCES hr.employees(employee_id),
    dept_id          INTEGER       NOT NULL REFERENCES hr.departments(dept_id),
    position_id      INTEGER       REFERENCES hr.positions(position_id),
    manager_id       INTEGER       REFERENCES hr.employees(employee_id),
    start_date       DATE          NOT NULL,
    end_date         DATE,
    transfer_type    VARCHAR(20)   NOT NULL DEFAULT 'hire',
    reason           TEXT,
    performance_after NUMERIC(3,1),
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_career_emp ON hr.career_history(employee_id);
CREATE INDEX idx_career_dept ON hr.career_history(dept_id);
CREATE INDEX idx_career_date ON hr.career_history(start_date);

COMMENT ON TABLE hr.career_history IS '社員の全配属履歴。transfer_type: hire/promotion/lateral/demotion/org_change';

-- 社員プロファイル拡張（履歴書・キャリア志向）
CREATE TABLE IF NOT EXISTS hr.employee_profiles (
    employee_id          INTEGER       PRIMARY KEY REFERENCES hr.employees(employee_id),
    education_level      VARCHAR(20),
    education_field      VARCHAR(100),
    university           VARCHAR(100),
    career_aspiration    TEXT,
    strengths_self       TEXT,
    preferred_dept_ids   INTEGER[],
    years_of_experience  INTEGER,
    previous_company_count INTEGER    DEFAULT 0,
    entry_type           VARCHAR(20)  NOT NULL DEFAULT 'new_grad',
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE hr.employee_profiles IS '履歴書・キャリア志向。entry_type: new_grad/mid_career/internal_transfer';

-- 1on1分析結果（Cortex AI による1on1メモの構造化分析）
CREATE TABLE IF NOT EXISTS hr.oneonone_analysis (
    analysis_id      SERIAL        PRIMARY KEY,
    note_id          INTEGER       NOT NULL UNIQUE REFERENCES hr.one_on_one_notes(note_id),
    employee_id      INTEGER       NOT NULL REFERENCES hr.employees(employee_id),
    manager_id       INTEGER       NOT NULL REFERENCES hr.employees(employee_id),
    sentiment_score  NUMERIC(4,3),
    topics           JSONB,
    concerns         TEXT[],
    positive_signals TEXT[],
    key_phrases      TEXT[],
    risk_signals     JSONB,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_oa_emp ON hr.oneonone_analysis(employee_id);
CREATE INDEX idx_oa_mgr ON hr.oneonone_analysis(manager_id);

COMMENT ON TABLE hr.oneonone_analysis IS '1on1メモのAI分析結果。risk_signals: [{type, severity, evidence_text}]';

-- 評価分析結果（Cortex AI による評価コメントの構造化分析）
CREATE TABLE IF NOT EXISTS hr.evaluation_analysis (
    analysis_id             SERIAL        PRIMARY KEY,
    evaluation_id           INTEGER       NOT NULL UNIQUE REFERENCES hr.evaluations(evaluation_id),
    employee_id             INTEGER       NOT NULL REFERENCES hr.employees(employee_id),
    sentiment_score         NUMERIC(4,3),
    self_sentiment_score    NUMERIC(4,3),
    sentiment_gap           NUMERIC(4,3),
    extracted_strengths     TEXT[],
    extracted_improvements  TEXT[],
    extracted_career_signals TEXT[],
    category                VARCHAR(30),
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ea_emp ON hr.evaluation_analysis(employee_id);

COMMENT ON TABLE hr.evaluation_analysis IS '評価コメントのAI分析結果。category: growth/stable/declining/critical';

-- 360度フィードバック（ピアレビュー）
CREATE TABLE IF NOT EXISTS hr.peer_feedback (
    feedback_id        SERIAL       PRIMARY KEY,
    employee_id        INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    reviewer_id        INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    reviewer_relation  VARCHAR(20)  NOT NULL,
    period             VARCHAR(10)  NOT NULL,
    leadership_score   SMALLINT     CHECK (leadership_score BETWEEN 1 AND 5),
    collaboration_score SMALLINT    CHECK (collaboration_score BETWEEN 1 AND 5),
    communication_score SMALLINT    CHECK (communication_score BETWEEN 1 AND 5),
    expertise_score    SMALLINT     CHECK (expertise_score BETWEEN 1 AND 5),
    comment            TEXT,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE(employee_id, reviewer_id, period)
);

CREATE INDEX idx_pf_emp ON hr.peer_feedback(employee_id);
CREATE INDEX idx_pf_reviewer ON hr.peer_feedback(reviewer_id);
CREATE INDEX idx_pf_period ON hr.peer_feedback(period);

COMMENT ON TABLE hr.peer_feedback IS '360度フィードバック。reviewer_relation: peer/subordinate/cross_dept/self';

-- 評価コメントLLM定量化スコア
CREATE TABLE IF NOT EXISTS hr.eval_quantified_scores (
    id                    SERIAL        PRIMARY KEY,
    evaluation_id         INTEGER       NOT NULL UNIQUE REFERENCES hr.evaluations(evaluation_id),
    employee_id           INTEGER       NOT NULL REFERENCES hr.employees(employee_id),
    period                VARCHAR(10)   NOT NULL,
    growth_score          SMALLINT      CHECK (growth_score BETWEEN 1 AND 5),
    expertise_score       SMALLINT      CHECK (expertise_score BETWEEN 1 AND 5),
    leadership_score      SMALLINT      CHECK (leadership_score BETWEEN 1 AND 5),
    problem_solving_score SMALLINT      CHECK (problem_solving_score BETWEEN 1 AND 5),
    collaboration_score   SMALLINT      CHECK (collaboration_score BETWEEN 1 AND 5),
    composite_score       NUMERIC(3,1),
    ai_recommended_grade  VARCHAR(5),
    ai_reasoning          TEXT,
    manual_composite      NUMERIC(3,1),
    manual_grade          VARCHAR(5),
    manual_note           TEXT,
    dept_rank             INTEGER,
    grade_rank            INTEGER,
    model_version         VARCHAR(50)   DEFAULT 'claude-haiku-4-5',
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eqs_emp ON hr.eval_quantified_scores(employee_id);
CREATE INDEX IF NOT EXISTS idx_eqs_period ON hr.eval_quantified_scores(period);
CREATE INDEX IF NOT EXISTS idx_eqs_dept_rank ON hr.eval_quantified_scores(period, dept_rank);

COMMENT ON TABLE hr.eval_quantified_scores IS 'LLMによる評価コメント定量化。5軸スコア(1-5)+AI推薦グレード+手動上書き+順位';

-- 等級別の期待水準と重み（評価基準マスタ）
-- LLMは全社共通の絶対スケールで1-5を採点し、等級補正はしない。
-- 「良い」の基準は等級ごとに違うため、期待水準との差分で評価する。
CREATE TABLE IF NOT EXISTS hr.grade_score_standards (
    grade                    VARCHAR(5)   PRIMARY KEY,
    growth_expected          NUMERIC(2,1) NOT NULL CHECK (growth_expected BETWEEN 1 AND 5),
    growth_weight            NUMERIC(4,3) NOT NULL,
    expertise_expected       NUMERIC(2,1) NOT NULL CHECK (expertise_expected BETWEEN 1 AND 5),
    expertise_weight         NUMERIC(4,3) NOT NULL,
    leadership_expected      NUMERIC(2,1) NOT NULL CHECK (leadership_expected BETWEEN 1 AND 5),
    leadership_weight        NUMERIC(4,3) NOT NULL,
    problem_solving_expected NUMERIC(2,1) NOT NULL CHECK (problem_solving_expected BETWEEN 1 AND 5),
    problem_solving_weight   NUMERIC(4,3) NOT NULL,
    collaboration_expected   NUMERIC(2,1) NOT NULL CHECK (collaboration_expected BETWEEN 1 AND 5),
    collaboration_weight     NUMERIC(4,3) NOT NULL,
    sort_order               SMALLINT     NOT NULL,
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_by               VARCHAR(100),
    CONSTRAINT weights_sum_to_one CHECK (
      ABS(growth_weight + expertise_weight + leadership_weight
          + problem_solving_weight + collaboration_weight - 1.0) < 0.001)
);

COMMENT ON TABLE hr.grade_score_standards IS '等級別の期待水準(1-5)と重み(合計1.0)。基準変更は全員の順位を動かすため履歴を残す';

-- 基準の変更履歴（基準変更は全社の順位に影響するため監査対象）
CREATE TABLE IF NOT EXISTS hr.grade_score_standards_history (
    history_id  SERIAL       PRIMARY KEY,
    grade       VARCHAR(5)   NOT NULL,
    snapshot    JSONB        NOT NULL,
    changed_by  VARCHAR(100) NOT NULL,
    change_note TEXT,
    changed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gssh_grade ON hr.grade_score_standards_history(grade, changed_at DESC);

-- eval_quantified_scores の期待水準対応カラム
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS composite_raw        NUMERIC(3,1);
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS expectation_gap      NUMERIC(4,2);
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS standard_grade       VARCHAR(5);
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS next_grade           VARCHAR(5);
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS next_grade_axes_met  SMALLINT;
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS promotion_readiness  VARCHAR(20);
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS promotion_shortfalls JSONB;

CREATE INDEX IF NOT EXISTS idx_eqs_gap ON hr.eval_quantified_scores(period, expectation_gap DESC);

COMMENT ON COLUMN hr.eval_quantified_scores.expectation_gap IS 'Σ(weight×(actual−expected))。0=期待通り。順位の主指標。等級をまたいで比較可能';
COMMENT ON COLUMN hr.eval_quantified_scores.composite_raw IS '5軸の単純平均。参照・監査用';
COMMENT ON COLUMN hr.eval_quantified_scores.standard_grade IS '適用した基準の等級。異動後も当時の計算根拠が追える';

-- 評価調整会議（部門横断で分布を揃える工程）
CREATE TABLE IF NOT EXISTS hr.calibration_sessions (
    session_id          SERIAL       PRIMARY KEY,
    session_name        VARCHAR(200) NOT NULL,
    period              VARCHAR(10)  NOT NULL,
    scope_dept_id       INTEGER      REFERENCES hr.departments(dept_id),
    target_distribution JSONB        NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'draft',
    facilitator         VARCHAR(100),
    notes               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finalized_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cs_period ON hr.calibration_sessions(period, status);

COMMENT ON TABLE hr.calibration_sessions IS '評価調整会議。scope_dept_id が NULL なら全社。status: draft/in_review/finalized';
COMMENT ON COLUMN hr.calibration_sessions.target_distribution IS '目標分布。例 {"S":0.05,"A":0.20,"B":0.50,"C":0.20,"D":0.05}';

-- 調整の記録（監査ログ兼務。理由は必須）
CREATE TABLE IF NOT EXISTS hr.calibration_adjustments (
    adjustment_id    SERIAL       PRIMARY KEY,
    session_id       INTEGER      NOT NULL REFERENCES hr.calibration_sessions(session_id),
    evaluation_id    INTEGER      NOT NULL REFERENCES hr.evaluations(evaluation_id),
    employee_id      INTEGER      NOT NULL REFERENCES hr.employees(employee_id),
    before_grade     VARCHAR(5),
    after_grade      VARCHAR(5),
    before_composite NUMERIC(3,1),
    after_composite  NUMERIC(3,1),
    reason           TEXT         NOT NULL,
    adjusted_by      VARCHAR(100) NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ca_session ON hr.calibration_adjustments(session_id);
CREATE INDEX IF NOT EXISTS idx_ca_emp ON hr.calibration_adjustments(employee_id);

COMMENT ON TABLE hr.calibration_adjustments IS '調整会議での個別グレード変更。理由必須で監査可能';


-- 既存テーブル拡張: employees に3カラム追加
ALTER TABLE hr.employees ADD COLUMN IF NOT EXISTS employment_type VARCHAR(20) DEFAULT 'regular';
ALTER TABLE hr.employees ADD COLUMN IF NOT EXISTS last_promotion_date DATE;
ALTER TABLE hr.employees ADD COLUMN IF NOT EXISTS commute_time_minutes INTEGER;
ALTER TABLE hr.employees ADD COLUMN IF NOT EXISTS entry_type VARCHAR(20) DEFAULT 'new_grad';  -- new_grad / mid_career

-- 既存テーブル拡張: evaluations に自己評価スコア追加
ALTER TABLE hr.evaluations ADD COLUMN IF NOT EXISTS self_score NUMERIC(3,1);

-- ============================================================================
-- 10d. PostgreSQL Row-Level Security（RLS）
-- ============================================================================

ALTER TABLE hr.employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE hr.evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE hr.one_on_one_notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY emp_dept_isolation ON hr.employees
    USING (
        current_setting('app.user_role', true) = 'HR_ADMIN'
        OR dept_id = ANY(
            string_to_array(current_setting('app.dept_scope', true), ',')::int[]
        )
    );

CREATE POLICY eval_dept_isolation ON hr.evaluations
    USING (
        current_setting('app.user_role', true) = 'HR_ADMIN'
        OR employee_id IN (
            SELECT employee_id FROM hr.employees
            WHERE dept_id = ANY(
                string_to_array(current_setting('app.dept_scope', true), ',')::int[]
            )
        )
    );

CREATE POLICY note_dept_isolation ON hr.one_on_one_notes
    USING (
        current_setting('app.user_role', true) = 'HR_ADMIN'
        OR employee_id IN (
            SELECT employee_id FROM hr.employees
            WHERE dept_id = ANY(
                string_to_array(current_setting('app.dept_scope', true), ',')::int[]
            )
        )
    );

COMMENT ON POLICY emp_dept_isolation ON hr.employees IS
    'FastAPIが SET app.user_role / app.dept_scope を設定し、部署スコープ外の社員を非表示にする';

-- ============================================================================
-- 11. サンプルデータ
-- ============================================================================

-- 11.1 部門
INSERT INTO hr.departments (dept_name, dept_code, parent_dept_id, level) VALUES
    ('代表取締役',    'CEO',   NULL, 0),
    ('営業本部',      'SALES', 1,    1),
    ('開発本部',      'DEV',   1,    1),
    ('管理本部',      'ADMIN', 1,    1),
    ('経営企画部',    'PLAN',  1,    1),
    ('第一営業部',    'SL01',  2,    2),
    ('第二営業部',    'SL02',  2,    2),
    ('プロダクト開発部','PD01', 3,    2),
    ('インフラ部',    'IF01',  3,    2),
    ('人事部',        'HR01',  4,    2),
    ('経理部',        'FI01',  4,    2),
    ('第一営業課',    'SL011', 6,    3),
    ('第二営業課',    'SL012', 6,    3),
    ('第三営業課',    'SL021', 7,    3)
ON CONFLICT DO NOTHING;

-- 11.2 スキル
INSERT INTO hr.skills (skill_name, category) VALUES
    ('Python',         'technical'),
    ('SQL',            'technical'),
    ('Java',           'technical'),
    ('JavaScript',     'technical'),
    ('AWS',            'technical'),
    ('プロジェクト管理', 'management'),
    ('チームマネジメント','management'),
    ('営業戦略',       'management'),
    ('英語',           'language'),
    ('中国語',         'language'),
    ('TOEIC 800+',     'certification'),
    ('PMP',            'certification'),
    ('簿記2級',        'certification'),
    ('データ分析',     'technical'),
    ('機械学習',       'technical')
ON CONFLICT DO NOTHING;

-- 11.3 ポジション（主要なもの）
INSERT INTO hr.positions (title, dept_id, grade, is_vacant, headcount) VALUES
    ('代表取締役社長',  1,  'E1', FALSE, 1),
    ('営業本部長',      2,  'D1', FALSE, 1),
    ('開発本部長',      3,  'D1', FALSE, 1),
    ('管理本部長',      4,  'D1', FALSE, 1),
    ('経営企画部長',    5,  'D2', FALSE, 1),
    ('第一営業部長',    6,  'D2', FALSE, 1),
    ('第二営業部長',    7,  'D2', FALSE, 1),
    ('PD部長',         8,  'D2', FALSE, 1),
    ('インフラ部長',    9,  'D2', FALSE, 1),
    ('人事部長',       10,  'D2', FALSE, 1),
    ('経理部長',       11,  'D2', FALSE, 1),
    ('営業課長',        12, 'M2', FALSE, 1),
    ('営業課長',        13, 'M2', FALSE, 1),
    ('営業課長',        14, 'M2', FALSE, 1),
    ('営業課長補佐',    12, 'S1', FALSE, 3),
    ('開発主査',        8,  'S2', FALSE, 5),
    ('開発主任',        8,  'J1', FALSE, 10),
    ('開発主事',        8,  'J2', FALSE, 10),
    ('インフラ主任',    9,  'J1', FALSE, 10),
    ('営業主任',        12, 'J1', FALSE, 10),
    ('人事主事',        10, 'J2', FALSE, 5),
    ('経理主事',        11, 'J2', FALSE, 5),
    ('新卒社員',        8,  'J3', FALSE, 5)
ON CONFLICT DO NOTHING;

-- 11.4 社員サンプル（20名 — 本番では2万名を合成データスクリプトで生成）
INSERT INTO hr.employees (employee_code, first_name, last_name, email, hire_date, birth_date, gender, dept_id, position_id, manager_id, status, salary) VALUES
    ('EMP001', '太郎',   '山田', 'yamada.taro@example.com',    '2005-04-01', '1975-03-15', 'M', 1,  1,  NULL, 'active', 30000000),
    ('EMP002', '花子',   '佐藤', 'sato.hanako@example.com',    '2008-04-01', '1978-07-22', 'F', 2,  2,  1,    'active', 18000000),
    ('EMP003', '一郎',   '鈴木', 'suzuki.ichiro@example.com',  '2010-04-01', '1980-11-30', 'M', 3,  3,  1,    'active', 17000000),
    ('EMP004', '二郎',   '高橋', 'takahashi.jiro@example.com', '2009-04-01', '1979-05-10', 'M', 4,  4,  1,    'active', 16000000),
    ('EMP005', '美咲',   '田中', 'tanaka.misaki@example.com',  '2012-04-01', '1982-01-25', 'F', 5,  5,  1,    'active', 14000000),
    ('EMP006', '健太',   '伊藤', 'ito.kenta@example.com',      '2011-04-01', '1983-09-05', 'M', 6,  6,  2,    'active', 12000000),
    ('EMP007', '由美',   '渡辺', 'watanabe.yumi@example.com',  '2013-04-01', '1985-04-18', 'F', 7,  7,  2,    'active', 12000000),
    ('EMP008', '大輔',   '中村', 'nakamura.daisuke@example.com','2014-04-01','1986-12-03', 'M', 8,  8,  3,    'active', 11000000),
    ('EMP009', '直樹',   '小林', 'kobayashi.naoki@example.com','2012-10-01', '1984-06-20', 'M', 9,  9,  3,    'active', 11000000),
    ('EMP010', '愛',     '加藤', 'kato.ai@example.com',        '2015-04-01', '1987-08-14', 'F', 10, 10, 4,    'active', 10000000),
    ('EMP011', '翔太',   '吉田', 'yoshida.shota@example.com',  '2016-04-01', '1990-02-28', 'M', 12, 12, 6,    'active', 8500000),
    ('EMP012', '麻衣',   '山口', 'yamaguchi.mai@example.com',  '2017-04-01', '1991-10-11', 'F', 13, 13, 6,    'active', 8500000),
    ('EMP013', '拓也',   '松本', 'matsumoto.takuya@example.com','2015-07-01','1988-03-07', 'M', 14, 14, 7,    'active', 8500000),
    ('EMP014', '彩香',   '井上', 'inoue.ayaka@example.com',    '2018-04-01', '1993-05-19', 'F', 12, 15, 11,   'active', 7000000),
    ('EMP015', '大地',   '木村', 'kimura.daichi@example.com',  '2019-04-01', '1994-09-23', 'M', 8,  16, 8,    'active', 7500000),
    ('EMP016', '遥',     '林',   'hayashi.haruka@example.com', '2020-04-01', '1996-01-12', 'F', 8,  17, 15,   'active', 5500000),
    ('EMP017', '蓮',     '清水', 'shimizu.ren@example.com',    '2021-04-01', '1997-07-07', 'M', 8,  17, 15,   'active', 5000000),
    ('EMP018', '結衣',   '森',   'mori.yui@example.com',       '2019-10-01', '1995-11-30', 'F', 12, 19, 11,   'active', 5500000),
    ('EMP019', '陸',     '阿部', 'abe.riku@example.com',       '2022-04-01', '1998-04-04', 'M', 9,  18, 9,    'active', 4800000),
    ('EMP020', '葵',     '橋本', 'hashimoto.aoi@example.com',  '2020-10-01', '1996-06-15', 'F', 10, 20, 10,   'active', 5200000)
ON CONFLICT DO NOTHING;

-- 11.5 スキル紐付け
INSERT INTO hr.employee_skills (employee_id, skill_id, proficiency, certified_at) VALUES
    (3,  1, 5, '2015-06-01'), (3,  2, 5, '2012-04-01'), (3,  5, 4, '2018-01-01'),
    (8,  1, 4, '2017-01-01'), (8,  4, 5, '2015-04-01'), (8,  6, 4, '2020-01-01'),
    (15, 1, 4, '2020-01-01'), (15, 2, 3, '2019-04-01'), (15, 15, 3, '2021-06-01'),
    (16, 4, 4, '2021-01-01'), (16, 1, 3, '2020-04-01'),
    (17, 1, 3, '2022-01-01'), (17, 14, 2, '2022-10-01'),
    (11, 8, 5, '2018-04-01'), (11, 7, 4, '2020-01-01'), (11, 9, 3, '2019-06-01'),
    (6,  8, 5, '2015-04-01'), (6,  7, 5, '2018-01-01'),
    (10, 7, 4, '2018-04-01'), (10, 12, 3, '2019-10-01'),
    (14, 8, 3, '2020-04-01'), (14, 2, 3, '2019-01-01')
ON CONFLICT DO NOTHING;

-- 11.6 評価サンプル
INSERT INTO hr.evaluations (employee_id, evaluator_id, period, score, grade, comment, status) VALUES
    (11, 6,  '2024H1', 4.0, 'A', '営業成績が目覚ましく、チームを牽引するリーダーシップが際立つ。新規クライアント獲得数は部門トップ。', 'confirmed'),
    (11, 6,  '2024H2', 4.2, 'A', '後輩の指導にも積極的で、チーム全体の底上げに貢献。戦略的思考力がさらに向上。', 'confirmed'),
    (11, 6,  '2025H1', 3.5, 'B', '成績は安定しているが、やや守りの姿勢が見える。新しい挑戦を促したい。', 'confirmed'),
    (11, 6,  '2025H2', 3.2, 'B', 'モチベーションの低下が気になる。キャリアパスについて面談が必要。', 'confirmed'),
    (16, 15, '2024H1', 3.8, 'A', 'フロントエンド開発において高い技術力を発揮。コードレビューも丁寧。', 'confirmed'),
    (16, 15, '2024H2', 4.0, 'A', 'React Flowを活用した新機能のプロトタイプを独力で完成。創造性が高い。', 'confirmed'),
    (16, 15, '2025H1', 4.2, 'S', '技術リーダーとしての頭角を現し始めた。社内勉強会も主催。', 'confirmed'),
    (17, 15, '2024H1', 3.0, 'B', 'Pythonの基礎は身についてきた。データ分析スキルの向上に期待。', 'confirmed'),
    (17, 15, '2025H1', 3.5, 'B', '機械学習の自主学習を進めており、成長意欲が高い。OJTを強化したい。', 'confirmed'),
    (14, 11, '2024H1', 3.5, 'B', '顧客対応が丁寧で信頼を得ている。数字への意識をさらに高めてほしい。', 'confirmed'),
    (14, 11, '2025H1', 3.2, 'B', '業務量の増加により疲労が見える。ワークライフバランスの改善が必要。', 'confirmed'),
    (6,  2,  '2024H1', 4.5, 'S', '部門の売上目標を120%達成。マネジメント能力も極めて高い。', 'confirmed'),
    (6,  2,  '2025H1', 4.3, 'S', '安定した部門運営。次期本部長候補として経営視点の強化を期待。', 'confirmed')
ON CONFLICT DO NOTHING;

-- 11.7 1on1メモサンプル
INSERT INTO hr.one_on_one_notes (employee_id, manager_id, note_date, content, category) VALUES
    (11, 6, '2025-06-15', 'キャリアについて悩んでいる様子。営業以外の道も考え始めているとのこと。新しいプロジェクトへのアサインを検討すると伝えた。', 'career'),
    (11, 6, '2025-09-20', '最近のモチベーション低下が顕著。同期の昇進に刺激を受けつつも焦りを感じている模様。メンタルケアが必要。', 'concern'),
    (11, 6, '2025-12-10', 'プロジェクトリーダーとしてのアサインを打診。前向きな反応あり。新規事業にも興味を示した。', 'motivation'),
    (16, 15, '2025-07-01', '技術力は申し分ない。マネジメントへの興味も出てきた。リーダーロールを少しずつ任せたい。', 'career'),
    (16, 15, '2025-10-15', '社内勉強会の企画運営を自発的に行っている。チームへの良い影響あり。', 'motivation'),
    (17, 15, '2025-08-01', 'Kaggleコンペに参加しているとのこと。学習意欲が高く好感が持てる。実務での機会を作りたい。', 'motivation'),
    (14, 11, '2025-05-20', '残業が増えており体調が心配。業務の優先順位付けについてアドバイスした。', 'concern'),
    (14, 11, '2025-11-01', '業務改善の提案があった。ツール導入による効率化に興味があるとのこと。', 'motivation'),
    -- 関係性スコアモデル用: 良好なペア（伊藤→部門メンバー）の1on1データ
    (18, 11, '2025-04-10', '目標設定について前向きな議論ができた。自発的に新しい顧客開拓の提案あり。', 'motivation'),
    (18, 11, '2025-06-20', '提案した営業手法が成果に繋がった。自信がついてきた様子。次は後輩指導にも挑戦したい。', 'motivation'),
    (18, 11, '2025-08-15', '半期の振り返り。成長を実感できているとのこと。来期は営業戦略の立案にも関わりたい。', 'career'),
    (18, 11, '2025-10-25', '顧客からの評価も高い。チームへの貢献意識が強く、良い影響を与えている。', 'motivation'),
    -- 関係性スコアモデル用: 懸念のあるペア（渡辺→部下）
    (13, 7,  '2025-05-10', '業務の進め方について意見が合わない場面が増えている。もう少し裁量を持たせてほしいとの要望。', 'concern'),
    (13, 7,  '2025-08-20', '前回の1on1から3ヶ月空いてしまった。コミュニケーション不足を感じる。', 'concern'),
    (13, 7,  '2025-12-05', '異動の希望を打ち明けられた。現在の業務にやりがいを感じにくいとのこと。', 'career'),
    -- 開発チーム: 良好な関係性パターン
    (17, 15, '2025-10-20', 'データ分析タスクを任せたところ、期待以上の成果。技術的な成長が著しい。', 'motivation'),
    (17, 15, '2025-12-15', '来期のプロジェクトでML関連のタスクをリードしたいとの申し出。前向きに検討。', 'career'),
    (16, 15, '2025-12-20', 'フロントエンドのアーキテクチャ刷新を主導。判断力と実行力に信頼を置ける。', 'motivation')
ON CONFLICT DO NOTHING;

-- 11.8 異動履歴サンプル（配置適合モデルの教師データ用）
INSERT INTO hr.transfer_requests (employee_id, from_dept_id, to_dept_id, from_position_id, to_position_id, reason, status, requested_by, approved_by, requested_at, resolved_at) VALUES
    (6,  7, 6, 14, 6, '営業力強化のため第一営業部長に抜擢', 'completed', 2, 1, '2018-10-01', '2018-10-15'),
    (8,  3, 8, NULL, 8, '新設のプロダクト開発部の立ち上げリーダーとして', 'completed', 3, 1, '2019-04-01', '2019-04-10'),
    (15, 8, 8, 17, 16, '開発エンジニアから開発リーダーへの昇進', 'completed', 8, 3, '2023-04-01', '2023-04-05'),
    (12, 6, 13, 15, 13, '第一営業部主任から第二営業課長へ昇進', 'completed', 6, 2, '2022-04-01', '2022-04-10')
ON CONFLICT DO NOTHING;

-- 11.8 アプリユーザー（パスワードはbcryptハッシュのプレースホルダー）
INSERT INTO hr.app_users (username, password_hash, role, employee_id, dept_scope) VALUES
    ('admin',   '$2b$12$placeholder_hash_admin',   'HR_ADMIN',   10, NULL),
    ('manager', '$2b$12$placeholder_hash_manager', 'HR_MANAGER', 6,  ARRAY[2,6,7,12,13]),
    ('viewer',  '$2b$12$placeholder_hash_viewer',  'HR_VIEWER',  18, ARRAY[12])
ON CONFLICT DO NOTHING;

-- ============================================================================
-- DONE
-- ============================================================================
-- 次のステップ:
-- 1. 2万件の合成データは Python スクリプト (generate_sample_data.py) で投入
-- 2. pg_lake を有効化して Snowflake Core への Iceberg 同期を開始

-- ============================================================
-- 以下は稼働中DBのカタログから生成（異動シナリオ・玉突き・確定データ・エージェント）
-- ============================================================

CREATE TABLE IF NOT EXISTS hr.whatif_scenarios (
    scenario_id SERIAL,
    scenario_name text NOT NULL,
    description text,
    created_by text,
    created_at timestamp with time zone DEFAULT now(),
    status character varying(30) NOT NULL DEFAULT 'draft'::character varying,
    reviewer_id integer,
    submitted_at timestamp with time zone,
    resolved_at timestamp with time zone,
    PRIMARY KEY (scenario_id)
);
CREATE INDEX IF NOT EXISTS idx_whatif_scen_status ON hr.whatif_scenarios USING btree (status);

CREATE TABLE IF NOT EXISTS hr.whatif_scenario_actions (
    action_id SERIAL,
    scenario_id integer,
    employee_id integer,
    from_dept_id integer,
    to_dept_id integer,
    from_position_id integer,
    to_position_id integer,
    action_type text,
    created_at timestamp with time zone DEFAULT now(),
    status character varying(20) NOT NULL DEFAULT 'pending'::character varying,
    reviewer_comment text,
    reviewed_at timestamp with time zone,
    revised_from_id integer,
    from_grade character varying(5),
    to_grade character varying(5),
    match_score smallint,
    match_reason text,
    PRIMARY KEY (action_id),
    FOREIGN KEY (scenario_id) REFERENCES hr.whatif_scenarios(scenario_id)
);
CREATE INDEX IF NOT EXISTS idx_whatif_act_status ON hr.whatif_scenario_actions USING btree (status);

CREATE TABLE IF NOT EXISTS hr.chain_simulations (
    simulation_id SERIAL,
    simulation_name text NOT NULL,
    trigger_type text,
    trigger_employee_id integer,
    created_by text,
    status text DEFAULT 'draft'::text,
    created_at timestamp with time zone DEFAULT now(),
    finalized_at timestamp with time zone,
    reviewer_id integer,
    submitted_at timestamp with time zone,
    resolved_at timestamp with time zone,
    PRIMARY KEY (simulation_id)
);
CREATE INDEX IF NOT EXISTS idx_chain_sim_status ON hr.chain_simulations USING btree (status);

CREATE TABLE IF NOT EXISTS hr.chain_simulation_steps (
    step_id SERIAL,
    simulation_id integer,
    step_order integer NOT NULL,
    employee_id integer,
    from_dept_id integer,
    to_dept_id integer,
    from_position_id integer,
    to_position_id integer,
    match_score double precision,
    ai_comment text,
    created_at timestamp with time zone DEFAULT now(),
    status character varying(20) DEFAULT 'pending'::character varying,
    reviewer_comment text,
    reviewed_at timestamp with time zone,
    PRIMARY KEY (step_id),
    FOREIGN KEY (simulation_id) REFERENCES hr.chain_simulations(simulation_id)
);

CREATE TABLE IF NOT EXISTS hr.scenario_snapshots (
    snapshot_id SERIAL,
    label text NOT NULL,
    effective_date date NOT NULL,
    snapshot_type character varying(20) NOT NULL,
    source_id integer,
    confirmed_by text,
    confirmed_at timestamp with time zone DEFAULT now(),
    data_json jsonb NOT NULL,
    PRIMARY KEY (snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_type ON hr.scenario_snapshots USING btree (snapshot_type);
CREATE INDEX IF NOT EXISTS idx_snapshot_date ON hr.scenario_snapshots USING btree (effective_date);

CREATE TABLE IF NOT EXISTS hr.agent_threads (
    thread_id text NOT NULL,
    title text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    messages jsonb DEFAULT '[]'::jsonb,
    parent_message_id text DEFAULT '0'::text,
    owner_username text,
    PRIMARY KEY (thread_id)
);
-- 既存環境向け（会話履歴は持ち主ごとに分ける）
ALTER TABLE hr.agent_threads ADD COLUMN IF NOT EXISTS owner_username text;
CREATE INDEX IF NOT EXISTS idx_agent_threads_owner ON hr.agent_threads(owner_username, updated_at DESC);

CREATE TABLE IF NOT EXISTS hr.user_feedback (
    feedback_id SERIAL,
    page character varying(100) NOT NULL,
    rating smallint NOT NULL,
    comment text,
    user_id character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (feedback_id),
    CHECK (((rating >= 1) AND (rating <= 5)))
);
CREATE INDEX IF NOT EXISTS idx_user_feedback_page ON hr.user_feedback USING btree (page);

-- 調整会議の対象等級（NULL = 全等級）
ALTER TABLE hr.calibration_sessions ADD COLUMN IF NOT EXISTS scope_grade text;

-- 上長（1stラインマネージャー）による評価入力
ALTER TABLE hr.evaluations ADD COLUMN IF NOT EXISTS grade_reason  text;
ALTER TABLE hr.evaluations ADD COLUMN IF NOT EXISTS submitted_at  timestamptz;
ALTER TABLE hr.evaluations ADD COLUMN IF NOT EXISTS return_reason text;
ALTER TABLE hr.evaluations ADD COLUMN IF NOT EXISTS returned_at   timestamptz;
-- AI が採点したときのコメント（提出時に変更がないか確認する）
ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS ai_input_comment text;

-- 5軸の手動修正（上長・人事）。eval_quantified_scores.*_score は修正後の値、AI の元値はここに残す
CREATE TABLE IF NOT EXISTS hr.eval_axis_overrides (
    evaluation_id integer     NOT NULL REFERENCES hr.evaluations(evaluation_id) ON DELETE CASCADE,
    axis          text        NOT NULL CHECK (axis IN ('growth','expertise','leadership','problem_solving','collaboration')),
    ai_score      numeric,
    manager_score numeric     NOT NULL CHECK (manager_score BETWEEN 1 AND 5),
    reason        text        NOT NULL,
    ai_changed    boolean     NOT NULL DEFAULT false,
    updated_by    text        NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (evaluation_id, axis)
);
