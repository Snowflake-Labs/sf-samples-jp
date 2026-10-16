#!/usr/bin/env python3
"""
上長（評価者）のデモ状態を作るスクリプト

ログインユーザー linemgr（内田洋平 課長, employee_id 8869）が「マイチーム評価」で
部下 8 名の 2025-H2 評価を入力する場面を用意する。generate_data.py の後に実行する。

- 8 名の 2025-H2 評価の評価者を内田洋平にする
- 状態: 未着手 5 名・下書き 2 名（佐藤紬、山本琴音）・提出済み 1 名（和田萌）
- AI 採点・上長修正・差し戻しの記録は消して、入力前の状態に戻す

社員は generate_data.py の固定シード（42）で決まるため、社員 ID で指定している。
何度実行しても同じ状態になる。
"""
import os

import psycopg2

CONN_PARAMS = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.environ["POSTGRES_USER"],
    "password": os.getenv("POSTGRES_PASSWORD"),
    "sslmode": "require",
}

LINE_MANAGER_ID = 8869  # 内田洋平（M2・部署 132）
PERIOD = "2025-H2"

# (employee_id, 状態, 上長コメント, 自己評価コメント, 自己評価点)
TEAM = [
    (8889, "not_started", None,
     "技術力の向上が著しく、難易度の高い案件も対応可能になった。", 3.5),          # 鈴木蓮 J1
    (8892, "draft",
     "プロジェクトの計画立案を任せた。スケジュールの見積もりが的確で、期限内に完了できた。",
     "プロジェクトの計画立案能力が向上している。", 3.5),                           # 佐藤紬 J1
    (8861, "not_started", None,
     "担当業務の手順を見直し、作業時間を短くできた。", 3.0),                         # 上田美咲 J2
    (8863, "not_started", None,
     "顧客からの信頼が厚く、対外的な評価も高い。", 3.5),                             # 中村新 J3
    (8853, "submitted",
     "担当顧客の要望を丁寧に聞き取り、提案の採用率を上げた。後輩の相談にもよく乗っている。",
     "担当顧客への提案の採用率が上がった。", 3.5),                                   # 和田萌 S1
    (8859, "not_started", None,
     "大口顧客の契約更新と追加2件を獲得した。新人2名のOJTを担当し、独り立ちさせた。", 4.0),  # 遠藤律 S1
    (8883, "not_started", None,
     "部門横断のプロジェクトで調整役を務め、予定どおり稼働させた。", 3.5),           # 木村大輔 S2
    (8851, "draft",
     "後輩の指導に積極的で、チームの",
     "後輩の指導に積極的に取り組んでいる。", 3.5),                                   # 山本琴音 S2
]


def main():
    conn = psycopg2.connect(**CONN_PARAMS)
    cur = conn.cursor()

    cur.execute("SELECT employee_id FROM hr.employees WHERE employee_id = %s", (LINE_MANAGER_ID,))
    if cur.fetchone() is None:
        raise SystemExit(f"employee_id {LINE_MANAGER_ID} がありません。先に generate_data.py を実行してください")

    team_ids = [t[0] for t in TEAM]
    cur.execute("""SELECT employee_id, evaluation_id FROM hr.evaluations
                   WHERE period = %s AND employee_id = ANY(%s)""", (PERIOD, team_ids))
    eval_ids = dict(cur.fetchall())

    # 評価がない社員には 2025-H2 の評価行を作る
    for emp_id in team_ids:
        if emp_id not in eval_ids:
            cur.execute("""INSERT INTO hr.evaluations (employee_id, evaluator_id, period, status)
                           VALUES (%s, %s, %s, 'draft') RETURNING evaluation_id""",
                        (emp_id, LINE_MANAGER_ID, PERIOD))
            eval_ids[emp_id] = cur.fetchone()[0]

    # 試験・デモで付いた AI 採点・上長修正を消す
    ids = list(eval_ids.values())
    cur.execute("DELETE FROM hr.eval_axis_overrides WHERE evaluation_id = ANY(%s)", (ids,))
    cur.execute("DELETE FROM hr.eval_quantified_scores WHERE evaluation_id = ANY(%s)", (ids,))

    for emp_id, state, comment, self_comment, self_score in TEAM:
        submitted = state == "submitted"
        cur.execute("""UPDATE hr.evaluations
                       SET evaluator_id = %s, comment = %s, self_comment = %s, self_score = %s,
                           status = %s, score = %s, grade = %s, grade_reason = NULL,
                           return_reason = NULL, returned_at = NULL,
                           submitted_at = CASE WHEN %s THEN TIMESTAMPTZ '2026-09-26 10:00:00+09' END,
                           updated_at = NOW()
                       WHERE evaluation_id = %s""",
                    (LINE_MANAGER_ID, comment, self_comment, self_score,
                     "submitted" if submitted else "draft",
                     3.5 if submitted else None, "B" if submitted else None,
                     submitted, eval_ids[emp_id]))

    conn.commit()
    cur.execute("""SELECT e.last_name || e.first_name, p.grade, ev.status, ev.comment IS NOT NULL
                   FROM hr.evaluations ev JOIN hr.employees e USING (employee_id)
                   JOIN hr.positions p ON p.position_id = e.position_id
                   WHERE ev.period = %s AND ev.evaluator_id = %s ORDER BY e.employee_code""",
                (PERIOD, LINE_MANAGER_ID))
    for name, grade, status, has_comment in cur.fetchall():
        print(f"  {name} ({grade}) status={status} comment={'あり' if has_comment else 'なし'}")
    cur.close()
    conn.close()
    print("完了!")


if __name__ == "__main__":
    main()
