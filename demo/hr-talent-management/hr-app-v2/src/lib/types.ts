export interface Employee {
  EMPLOYEE_ID: number;
  EMPLOYEE_CODE: string;
  FIRST_NAME: string;
  LAST_NAME: string;
  EMAIL: string;
  PHONE: string;
  HIRE_DATE: string;
  BIRTH_DATE: string;
  GENDER: string;
  DEPT_ID: number;
  POSITION_ID: number;
  MANAGER_ID: number | null;
  STATUS: string;
  SALARY: number;
  DEPT_NAME: string;
  POSITION_TITLE: string;
  GRADE: string;
}

export interface Department {
  DEPT_ID: number;
  DEPT_NAME: string;
  DEPT_CODE: string;
  PARENT_DEPT_ID: number | null;
  LEVEL: number;
  IS_ACTIVE: boolean;
}

export interface Position {
  POSITION_ID: number;
  TITLE: string;
  DEPT_ID: number;
  GRADE: string;
  IS_VACANT: boolean;
  HEADCOUNT: number;
}

export interface Evaluation {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  EVALUATOR_ID: number;
  PERIOD: string;
  SCORE: number;
  GRADE: string;
  COMMENT: string;
  SELF_COMMENT: string;
  STATUS: string;
  CREATED_AT: string;
  UPDATED_AT: string;
}

export interface Skill {
  EMPLOYEE_ID: number;
  SKILL_NAME: string;
  CATEGORY: string;
  PROFICIENCY: number;
}

export interface OneOnOneNote {
  NOTE_ID: number;
  EMPLOYEE_ID: number;
  MANAGER_ID: number;
  NOTE_DATE: string;
  CONTENT: string;
  CATEGORY: string;
  IS_PRIVATE: boolean;
}

export interface TransferRequest {
  REQUEST_ID: number;
  EMPLOYEE_ID: number;
  FROM_DEPT_ID: number;
  TO_DEPT_ID: number;
  FROM_POSITION_ID: number;
  TO_POSITION_ID: number;
  REASON: string;
  STATUS: string;
  REQUESTED_BY: number;
  APPROVED_BY: number;
  REQUESTED_AT: string;
  RESOLVED_AT: string;
}

export interface AppUser {
  USER_ID: number;
  USERNAME: string;
  ROLE: string;
  EMPLOYEE_ID: number;
  DEPT_SCOPE: string;
  IS_ACTIVE: boolean;
}

export type UserRole = "HR_ADMIN" | "HR_MANAGER" | "HR_VIEWER" | "LINE_MANAGER";

/**
 * Roles arrive from hr.app_users as free-form text and have historically
 * been stored in several shapes ("hr_admin", "manager", "HR_VIEWER").
 * Normalize at the session boundary so authorization compares like with
 * like — otherwise every role check silently denies.
 *
 * Unknown values fall back to the least-privileged role rather than
 * defaulting to admin.
 */
const ROLE_ALIASES: Record<string, UserRole> = {
  hr_admin: "HR_ADMIN",
  admin: "HR_ADMIN",
  hr_manager: "HR_MANAGER",
  manager: "HR_MANAGER",
  hr_viewer: "HR_VIEWER",
  viewer: "HR_VIEWER",
  line_manager: "LINE_MANAGER",
};

export function normalizeRole(raw: unknown): UserRole {
  const key = String(raw ?? "").trim().toLowerCase();
  const mapped = ROLE_ALIASES[key];
  if (!mapped) {
    console.warn(`[auth] unknown role ${JSON.stringify(raw)}; falling back to HR_VIEWER`);
    return "HR_VIEWER";
  }
  return mapped;
}

export interface SessionUser {
  userId: number;
  username: string;
  role: UserRole;
  employeeId: number;
  deptScope: number[] | null;
  displayName: string;
}

export const GRADE_ORDER = ["E1", "D1", "D2", "M1", "M2", "S1", "S2", "J1", "J2", "J3"];
// hr.positions の役職名（多い順）に合わせた等級の呼び方。1等級に複数の役職名があるので「〜級」で表す
export const GRADE_LABELS: Record<string, string> = {
  E1: "役員",            // 取締役・執行役員
  D1: "本部長級",        // 統括部長・事業部長・本部長
  D2: "部長級",          // 担当部長・副部長・部長
  M1: "課長級",          // センター長・室長・課長
  M2: "課長代理級",      // 主幹・グループリーダー・課長代理
  S1: "係長級",          // 係長・主任・チームリーダー
  S2: "副主任級",        // 副主任・上級専門職
  J1: "一般（上級）",    // 専門職・一般社員(上級)
  J2: "一般（中級）",    // 一般社員(中級)・社員
  J3: "一般（初級）",    // アシスタント・一般社員(初級)・新入社員
};

export const ML_MODEL_METRICS = {
  ATTRITION_AUC: 0.937,
  RELATIONSHIP_RMSE: 0.081,
  TRANSFER_FIT_RMSE: 0.0373,
} as const;

export const FEATURE_LABELS: Record<string, string> = {
  TENURE_MONTHS: "勤続月数",
  AVG_EVAL_SCORE: "平均評価スコア",
  EVAL_TREND: "評価推移",
  RISK_SIGNAL_COUNT: "リスクシグナル数",
  CAREER_CHANGE_COUNT: "キャリア変更回数",
  SENTIMENT_AVG: "感情スコア平均",
  SENTIMENT_TREND: "感情トレンド",
  MONTHS_SINCE_PROMOTION: "昇進後経過月数",
  TEAM_SIZE: "チーム人数",
  PREVIOUS_COMPANY_COUNT: "前職数",
  COMMUTE_TIME_MINUTES: "通勤時間(分)",
  SELF_EVAL_GAP: "自己評価ギャップ",
  PEER_COLLAB_SCORE: "ピア協調性",
  EVAL_CATEGORY_LATEST: "最新評価カテゴリ",
};

export const FEATURE_DESCRIPTIONS: Record<string, string> = {
  TENURE_MONTHS: "入社からの経過月数。短いと早期離職リスク、長すぎるとマンネリ化リスクの指標",
  AVG_EVAL_SCORE: "直近の人事評価スコアの平均値（1〜5）。低いと不満蓄積の可能性",
  EVAL_TREND: "評価スコアの変化傾向。負の値は評価低下を示し、モチベーション低下と相関",
  RISK_SIGNAL_COUNT: "1on1メモや面談記録から検出されたリスクシグナルの数",
  CAREER_CHANGE_COUNT: "過去の部署異動・職種変更の回数。多いと定着しにくい傾向",
  SENTIMENT_AVG: "1on1メモのテキストから算出した感情スコアの平均（-1〜1）",
  SENTIMENT_TREND: "感情スコアの変化傾向。負の値は感情の悪化を示す",
  MONTHS_SINCE_PROMOTION: "最後の昇進からの経過月数。長いと昇進停滞による不満の指標",
  TEAM_SIZE: "所属チームの人数。極端に大きい/小さいとストレス要因になりうる",
  PREVIOUS_COMPANY_COUNT: "転職回数。多いほど再度の転職リスクが高い傾向",
  COMMUTE_TIME_MINUTES: "自宅から職場までの通勤時間（分）。長いと離職リスク上昇",
  SELF_EVAL_GAP: "自己評価と上司評価の乖離。大きいと不満や認識ギャップの指標",
  PEER_COLLAB_SCORE: "同僚からの協調性評価スコア。低いとチーム内の人間関係に課題",
  EVAL_CATEGORY_LATEST: "直近の評価カテゴリ（S/A/B/C/D）を数値化した値",
  ONEONONE_SENTIMENT_AVG: "1on1面談テキストから算出した感情スコアの平均",
  AGE_DIFF: "上司との年齢差（歳）。大きいとコミュニケーションギャップの可能性",
  EVAL_GAP: "上司と部下の評価スコア差。大きいと評価の公平性に課題",
  PAIR_TENURE_MONTHS: "現在の上司-部下ペアとしての継続月数。短いと関係構築途上",
  SUBORDINATE_LEADERSHIP_SCORE: "部下から見た上司のリーダーシップ評価スコア",
};
