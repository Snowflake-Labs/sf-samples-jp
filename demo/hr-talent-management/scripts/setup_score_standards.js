const { Pool } = require("pg");

// Connection comes from the same env vars as the app (see .env.example).
for (const k of ["POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD"]) {
  if (!process.env[k]) { console.error(`${k} is not set`); process.exit(1); }
}
const pool = new Pool({
  host: process.env.POSTGRES_HOST,
  port: Number(process.env.POSTGRES_PORT || 5432),
  database: process.env.POSTGRES_DB || "postgres",
  user: process.env.POSTGRES_USER,
  password: process.env.POSTGRES_PASSWORD,
  ssl: { rejectUnauthorized: false },
});

// grade, sort, [growth, expertise, leadership, problem_solving, collaboration]
// each axis is [expected, weight]
const STANDARDS = [
  ["E1", 1, [3.0, 0.05], [4.0, 0.15], [4.8, 0.45], [4.5, 0.25], [3.5, 0.10]],
  ["D1", 2, [3.0, 0.05], [4.0, 0.15], [4.5, 0.45], [4.3, 0.25], [3.5, 0.10]],
  ["D2", 3, [3.2, 0.10], [3.8, 0.20], [4.0, 0.35], [4.0, 0.25], [3.5, 0.10]],
  ["M1", 4, [3.3, 0.10], [3.7, 0.20], [3.7, 0.35], [3.8, 0.25], [3.5, 0.10]],
  ["M2", 5, [3.5, 0.15], [3.5, 0.25], [3.3, 0.25], [3.5, 0.20], [3.5, 0.15]],
  ["S1", 6, [3.5, 0.15], [3.3, 0.25], [3.0, 0.25], [3.3, 0.20], [3.3, 0.15]],
  ["S2", 7, [3.5, 0.25], [3.2, 0.30], [2.5, 0.10], [3.0, 0.20], [3.2, 0.15]],
  ["J1", 8, [3.5, 0.25], [3.0, 0.30], [2.2, 0.10], [2.8, 0.20], [3.0, 0.15]],
  ["J2", 9, [3.3, 0.35], [2.7, 0.30], [1.8, 0.05], [2.5, 0.15], [3.0, 0.15]],
  ["J3", 10, [3.0, 0.35], [2.0, 0.30], [1.5, 0.05], [2.0, 0.15], [3.0, 0.15]],
];

async function main() {
  // Sanity: weights must sum to 1.0 before we let the DB reject them
  for (const [grade, , g, e, l, p, c] of STANDARDS) {
    const sum = g[1] + e[1] + l[1] + p[1] + c[1];
    if (Math.abs(sum - 1.0) > 0.001) {
      throw new Error(`${grade} weights sum to ${sum}, not 1.0`);
    }
  }

  await pool.query(`
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
    )
  `);
  console.log("grade_score_standards created");

  await pool.query(`
    CREATE TABLE IF NOT EXISTS hr.grade_score_standards_history (
      history_id  SERIAL       PRIMARY KEY,
      grade       VARCHAR(5)   NOT NULL,
      snapshot    JSONB        NOT NULL,
      changed_by  VARCHAR(100) NOT NULL,
      change_note TEXT,
      changed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
  `);
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_gssh_grade ON hr.grade_score_standards_history(grade, changed_at DESC)`);
  console.log("grade_score_standards_history created");

  for (const [grade, sort, g, e, l, p, c] of STANDARDS) {
    await pool.query(
      `INSERT INTO hr.grade_score_standards
         (grade, growth_expected, growth_weight, expertise_expected, expertise_weight,
          leadership_expected, leadership_weight, problem_solving_expected, problem_solving_weight,
          collaboration_expected, collaboration_weight, sort_order, updated_by)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'system-seed')
       ON CONFLICT (grade) DO NOTHING`,
      [grade, g[0], g[1], e[0], e[1], l[0], l[1], p[0], p[1], c[0], c[1], sort]
    );
  }
  console.log("standards seeded");

  // eval_quantified_scores extensions
  const cols = [
    ["composite_raw", "NUMERIC(3,1)"],
    ["expectation_gap", "NUMERIC(4,2)"],
    ["standard_grade", "VARCHAR(5)"],
    ["next_grade", "VARCHAR(5)"],
    ["next_grade_axes_met", "SMALLINT"],
    ["promotion_readiness", "VARCHAR(20)"],
    ["promotion_shortfalls", "JSONB"],
  ];
  for (const [name, type] of cols) {
    await pool.query(`ALTER TABLE hr.eval_quantified_scores ADD COLUMN IF NOT EXISTS ${name} ${type}`);
  }
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_eqs_gap ON hr.eval_quantified_scores(period, expectation_gap DESC)`);
  console.log("eval_quantified_scores extended");

  const { rows } = await pool.query(
    `SELECT grade, growth_expected, leadership_expected, leadership_weight, sort_order
     FROM hr.grade_score_standards ORDER BY sort_order`
  );
  console.table(rows);

  await pool.end();
}

main().catch((e) => {
  console.error(e.message);
  pool.end();
  process.exit(1);
});
