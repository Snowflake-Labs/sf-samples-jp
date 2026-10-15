#!/usr/bin/env python3
"""
ML パイプラインの入力データを Postgres に作るスクリプト

generate_data.py の後に実行する。作るのは次の 5 テーブル（すべて架空データ）:
- career_history       配属・異動の履歴（入社配属 + 異動 0〜3 回）
- employee_profiles    学歴・キャリア志向・前職社数
- peer_feedback        360 度フィードバック（3 期分）
- evaluation_analysis  評価コメントの感情スコアとカテゴリ
- oneonone_analysis    1on1 メモの感情スコア・トピック・リスク信号

本来の分析テーブル（evaluation_analysis / oneonone_analysis）は Cortex AI で
コメントを読んで作る想定だが、コメント自体が生成データなので、ここでは評価点から
決まる値に揺らぎを足して作る（Cortex のコストをかけずに再現できるようにするため）。

乱数は独自のシードで回し、generate_data.py が作ったデータには触れない。
何度実行しても同じ結果になる（各テーブルを空にしてから入れ直す）。
"""
import json
import os
import random
from datetime import date, timedelta

import psycopg2
from psycopg2.extras import execute_values

CONN_PARAMS = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.environ["POSTGRES_USER"],
    "password": os.getenv("POSTGRES_PASSWORD"),
    "sslmode": "require",
}

rng = random.Random(20260314)
BATCH = 5000
TODAY = date(2026, 3, 16)

TRANSFER_REASONS = {
    "lateral": ["専門性向上のため", "キャリア開発のため", "組織改編に伴う異動", "本人希望による異動"],
    "promotion": ["業績評価に基づく昇進", "後進育成のため", "マネジメント経験付与", "キャリア開発のため"],
    "org_change": ["組織改編に伴う異動", "新規事業立ち上げ", "業務統合に伴う異動", "マネジメント経験付与"],
}
EDU_LEVELS = [("bachelor", 60), ("master", 24), ("high_school", 11), ("doctorate", 5)]
EDU_FIELDS = ["経済学", "経営学", "商学", "法学", "文学", "社会学", "教育学", "理学", "工学",
              "情報工学", "数学", "統計学", "農学", "薬学", "医学"]
UNIVERSITIES = ["北海道大学", "東北大学", "東京大学", "一橋大学", "東京工業大学", "名古屋大学",
                "京都大学", "大阪大学", "神戸大学", "九州大学", "早稲田大学", "慶應義塾大学",
                "上智大学", "明治大学", "青山学院大学", "立教大学", "中央大学", "法政大学",
                "学習院大学", "日本大学", "同志社大学", "立命館大学", "関西大学", "関西学院大学",
                "北海学園大学"]
ASPIRATIONS = [
    "営業部門でのマネジメント経験を積み、将来的には本部長を目指したい",
    "専門性を深め、データ分析のスペシャリストとして組織に貢献したい",
    "顧客接点の最前線で経験を積み、サービス品質の向上に貢献したい",
    "IT戦略の推進を通じて、デジタルトランスフォーメーションに貢献したい",
    "人事・組織開発の分野でキャリアを築き、社員の成長を支援したい",
    "経営企画部門で戦略立案に関わり、会社の方向性を決める立場になりたい",
    "リスク管理・コンプライアンスの専門家として経営を支えたい",
    "海外事業に携わり、グローバルな視点でビジネスを推進したい",
    "アクチュアリーとしての専門資格を取得し、商品開発に携わりたい",
    "現場のマネジメントを通じて、チーム全体の成果を最大化したい",
]
STRENGTHS = ["粘り強く最後までやり遂げる", "関係者を巻き込んで物事を進める", "数字に強く分析が得意",
             "新しいことを素早く学べる", "丁寧な顧客対応", "論理的に説明できる"]
PEER_PERIODS = ["2024-H2", "2025-H1", "2025-H2"]
PEER_COMMENTS = [
    "リーダーシップがあり、プロジェクトを推進する力がある。",
    "コミュニケーション能力が高く、部門間の橋渡しをしてくれる。",
    "専門知識が豊富で、相談するといつも的確なアドバイスをもらえる。",
    "チームの雰囲気作りに貢献してくれている。困った時にいつも助けてくれる。",
    "真面目で責任感が強い。任された仕事は必ずやり遂げる。",
    "成長意欲が高く、常に新しいことに挑戦している姿勢が素晴らしい。",
    "後輩の面倒見がよく、チーム全体の底上げに貢献している。",
    "技術力は高いが、チームワークの面で改善の余地がある。",
    "もう少し積極的に意見を発信してほしい。",
    "時々周囲への配慮が不足することがある。",
]
TOPICS = ["career", "workload", "performance", "team_dynamics", "personal_development",
          "skill_development", "project_update", "feedback", "work_life_balance"]
RISK_TYPES = ["burnout", "job_dissatisfaction", "external_interest", "relationship_issue"]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def weighted(choices):
    total = sum(w for _, w in choices)
    r = rng.uniform(0, total)
    for value, w in choices:
        r -= w
        if r <= 0:
            return value
    return choices[-1][0]


def insert(cur, sql, rows):
    for i in range(0, len(rows), BATCH):
        execute_values(cur, sql, rows[i:i + BATCH])


def main():
    conn = psycopg2.connect(**CONN_PARAMS)
    cur = conn.cursor()
    cur.execute("SET search_path = hr")

    print("既存データクリア中...")
    for tbl in ["oneonone_analysis", "evaluation_analysis", "peer_feedback",
                "employee_profiles", "career_history"]:
        cur.execute(f"TRUNCATE TABLE hr.{tbl} RESTART IDENTITY")

    cur.execute("""SELECT e.employee_id, e.dept_id, e.position_id, e.manager_id, e.hire_date,
                          e.birth_date, e.entry_type, p.grade
                   FROM hr.employees e LEFT JOIN hr.positions p ON p.position_id = e.position_id
                   ORDER BY e.employee_id""")
    employees = cur.fetchall()
    cur.execute("SELECT position_id, dept_id, grade FROM hr.positions ORDER BY position_id")
    positions = cur.fetchall()
    pos_by_grade = {}
    for pid, did, grade in positions:
        pos_by_grade.setdefault(grade, []).append((pid, did))
    dept_ids = sorted({d for _, d, _ in positions})
    cur.execute("""SELECT employee_id, AVG(score)::float FROM hr.evaluations
                   WHERE score IS NOT NULL GROUP BY employee_id""")
    avg_score = dict(cur.fetchall())

    # ---- career_history: 入社配属 + 0〜3 回の異動。最後の 1 件が現在の配属 ----
    print("career_history 生成中...")
    rows = []
    for emp_id, dept_id, pos_id, mgr_id, hire_date, _, _, grade in employees:
        n_moves = weighted([(0, 62), (1, 25), (2, 10), (3, 3)])
        if hire_date is None or (TODAY - hire_date).days < 365 * (n_moves + 1):
            n_moves = 0
        span = (TODAY - hire_date).days
        cuts = sorted(rng.sample(range(180, max(span - 90, 181)), n_moves)) if n_moves else []
        starts = [hire_date] + [hire_date + timedelta(days=c) for c in cuts]
        for i, start in enumerate(starts):
            last = i == len(starts) - 1
            end = None if last else starts[i + 1] - timedelta(days=1)
            if i == 0:
                ttype, reason, perf = "hire", "入社配属", None
            else:
                ttype = weighted([("lateral", 50), ("promotion", 25), ("org_change", 25)])
                reason = rng.choice(TRANSFER_REASONS[ttype])
                perf = round(clamp(rng.gauss(3.5, 0.6), 1.0, 5.0), 1)
            if last:
                d, p = dept_id, pos_id
            else:
                p, d = rng.choice(pos_by_grade.get(grade) or positions[:1])[:2]
            rows.append((emp_id, d, p, mgr_id if last else None, start, end, ttype, reason, perf))
    insert(cur, """INSERT INTO hr.career_history (employee_id, dept_id, position_id, manager_id,
                   start_date, end_date, transfer_type, reason, performance_after) VALUES %s""", rows)
    print(f"  career_history: {len(rows):,}")

    # ---- employee_profiles ----
    print("employee_profiles 生成中...")
    rows = []
    for emp_id, _, _, _, hire_date, birth_date, entry_type, _ in employees:
        edu = weighted(EDU_LEVELS)
        field = None if edu == "high_school" else rng.choice(EDU_FIELDS)
        univ = None if edu == "high_school" else rng.choice(UNIVERSITIES)
        mid = entry_type == "mid_career"
        prev = rng.randint(1, 4) if mid else 0
        years = max(0, (TODAY - hire_date).days // 365 + (rng.randint(2, 12) if mid else 0))
        aspiration = None if rng.random() < 0.09 else rng.choice(ASPIRATIONS)
        strengths = rng.choice(STRENGTHS) if rng.random() < 0.12 else None
        preferred = rng.sample(dept_ids, rng.randint(1, 3))
        rows.append((emp_id, edu, field, univ, aspiration, strengths, preferred, years, prev,
                     entry_type or "new_grad"))
    insert(cur, """INSERT INTO hr.employee_profiles (employee_id, education_level, education_field,
                   university, career_aspiration, strengths_self, preferred_dept_ids,
                   years_of_experience, previous_company_count, entry_type) VALUES %s""", rows)
    print(f"  employee_profiles: {len(rows):,}")

    # ---- peer_feedback: 同じ部署の同僚・他部署・部下から、期ごとに約 1〜2 件 ----
    print("peer_feedback 生成中...")
    by_dept = {}
    subordinates = {}
    for emp_id, dept_id, _, mgr_id, *_ in employees:
        by_dept.setdefault(dept_id, []).append(emp_id)
        if mgr_id:
            subordinates.setdefault(mgr_id, []).append(emp_id)
    all_ids = [e[0] for e in employees]
    rows = []
    seen = set()
    for emp_id, dept_id, *_ in employees:
        base = avg_score.get(emp_id, 3.3)
        for period in PEER_PERIODS:
            reviewers = []
            if subordinates.get(emp_id):
                reviewers += ["subordinate"] * rng.randint(1, 2)
            reviewers += [None] * weighted([(1, 55), (2, 35), (0, 10)])
            for kind in reviewers:
                if kind == "subordinate":
                    relation, reviewer = "subordinate", rng.choice(subordinates[emp_id])
                elif rng.random() < 0.5 and len(by_dept[dept_id]) > 1:
                    relation, reviewer = "peer", rng.choice(by_dept[dept_id])
                else:
                    relation, reviewer = "cross_dept", rng.choice(all_ids)
                if reviewer == emp_id or (emp_id, reviewer, period) in seen:
                    continue
                seen.add((emp_id, reviewer, period))
                s = [int(clamp(round(rng.gauss(base + 0.2, 1.0)), 1, 5)) for _ in range(4)]
                rows.append((emp_id, reviewer, relation, period, *s, rng.choice(PEER_COMMENTS)))
    insert(cur, """INSERT INTO hr.peer_feedback (employee_id, reviewer_id, reviewer_relation, period,
                   leadership_score, collaboration_score, communication_score, expertise_score,
                   comment) VALUES %s""", rows)
    print(f"  peer_feedback: {len(rows):,}")

    # ---- evaluation_analysis: 評価点からカテゴリと感情スコアを決める ----
    print("evaluation_analysis 生成中...")
    cur.execute("""SELECT evaluation_id, employee_id, score::float FROM hr.evaluations
                   WHERE score IS NOT NULL ORDER BY evaluation_id""")
    rows = []
    for eval_id, emp_id, score in cur.fetchall():
        # 区切りは評価点の分布に合わせ、growth 45% / stable 27% / declining 18% / critical 10% 程度にする
        z = score + rng.gauss(0, 0.3)
        category = ("growth" if z >= 3.45 else "stable" if z >= 2.85
                    else "declining" if z >= 2.3 else "critical")
        center = {"growth": 0.6, "stable": 0.15, "declining": -0.15, "critical": -0.5}[category]
        sent = round(clamp(rng.gauss(center, 0.18), -1, 1), 3)
        self_sent = round(clamp(rng.gauss(0.3, 0.2), -1, 1), 3)
        rows.append((eval_id, emp_id, sent, self_sent, round(sent - self_sent, 3), category))
    insert(cur, """INSERT INTO hr.evaluation_analysis (evaluation_id, employee_id, sentiment_score,
                   self_sentiment_score, sentiment_gap, category) VALUES %s""", rows)
    print(f"  evaluation_analysis: {len(rows):,}")

    # ---- oneonone_analysis: メモ 1 件ごとに感情・トピック 2 個・まれにリスク信号 ----
    print("oneonone_analysis 生成中...")
    cur.execute("""SELECT note_id, employee_id, manager_id, content FROM hr.one_on_one_notes
                   ORDER BY note_id""")
    rows = []
    for note_id, emp_id, mgr_id, content in cur.fetchall():
        mood = (avg_score.get(emp_id, 3.3) - 3.3) * 0.5
        sent = round(clamp(rng.gauss(0.3 + mood, 0.35), -1, 1), 3)
        weights = sorted([rng.uniform(0.2, 0.8), rng.uniform(0.2, 0.8)], reverse=True)
        topics = [{"topic": t, "weight": round(w, 2)}
                  for t, w in zip(rng.sample(TOPICS, 2), weights)]
        risks = []
        if (sent < 0 and rng.random() < 0.12) or rng.random() < 0.015:
            risks.append({"type": rng.choice(RISK_TYPES),
                          "severity": weighted([("low", 40), ("medium", 35), ("high", 25)]),
                          "evidence_text": (content or "")[:60]})
        rows.append((note_id, emp_id, mgr_id, sent, json.dumps(topics, ensure_ascii=False),
                     json.dumps(risks, ensure_ascii=False)))
    insert(cur, """INSERT INTO hr.oneonone_analysis (note_id, employee_id, manager_id, sentiment_score,
                   topics, risk_signals) VALUES %s""", rows)
    print(f"  oneonone_analysis: {len(rows):,}")

    conn.commit()
    cur.close()
    conn.close()
    print("完了!")


if __name__ == "__main__":
    main()
