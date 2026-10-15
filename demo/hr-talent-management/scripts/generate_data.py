#!/usr/bin/env python3
"""
HR Demo データ生成スクリプト
デモ用の架空データを Postgres に投入する
- DEPARTMENTS: 191 (Level 0:1, Level 1:48, Level 2:142)
- EMPLOYEES: 15,213 (active:14,071, inactive:1,142)
- POSITIONS: ~1,195 (10等級 × 各部署)
- EVALUATIONS: ~42,410 (4期間)
- ONE_ON_ONE_NOTES: ~35,201
- SKILLS: 30
- EMPLOYEE_SKILLS: ~53,251
- TRANSFER_REQUESTS: 1,500
"""

import os
import random
import string
from datetime import date, timedelta
import psycopg2
from psycopg2.extras import execute_values

random.seed(42)

CONN_PARAMS = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.environ["POSTGRES_USER"],
    "password": os.getenv("POSTGRES_PASSWORD"),
    "sslmode": "require",
}

LAST_NAMES = [
    "佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤",
    "吉田", "山田", "佐々木", "松本", "井上", "木村", "林", "清水", "山崎", "阿部",
    "森", "池田", "橋本", "山口", "石川", "前田", "藤田", "小川", "岡田", "後藤",
    "長谷川", "石井", "村上", "近藤", "坂本", "遠藤", "青木", "藤井", "西村", "福田",
    "太田", "三浦", "藤原", "岡本", "松田", "中島", "中川", "原田", "竹内", "金子",
    "河野", "和田", "中野", "上田", "小野", "田村", "石田", "大野", "菅原", "宮崎",
    "安藤", "松井", "横山", "杉山", "野村", "内田", "千葉", "久保", "杉本", "今井",
    "堀", "北村", "浜田", "武田", "桜井", "新井", "渡部", "野口", "酒井", "松尾",
]
FIRST_NAMES_M = [
    "太郎", "健一", "翔太", "大輔", "拓也", "直樹", "和也", "裕二", "隆", "浩",
    "誠", "修", "学", "剛", "亮", "洋平", "康平", "智也", "英樹", "正人",
    "雄一", "秀樹", "勝", "達也", "光一", "真一", "圭介", "敏夫", "清", "博",
    "悠太", "蓮", "大翔", "湊", "陽翔", "律", "朝陽", "碧", "新", "結翔",
]
FIRST_NAMES_F = [
    "花子", "愛", "由美子", "真由美", "陽子", "裕子", "恵子", "明美", "久美子", "典子",
    "幸子", "和子", "美咲", "さくら", "千尋", "綾香", "友香", "恵", "美穂", "智子",
    "彩", "舞", "紗希", "奈々", "萌", "遥", "理沙", "瞳", "楓", "詩織",
    "凛", "結月", "陽菜", "芽依", "紬", "莉子", "結菜", "咲良", "美月", "琴音",
]

AREA_HONBU = [
    "北海道エリア本部", "東北エリア本部", "北関東エリア本部", "南関東エリア本部",
    "東京エリア本部", "横浜エリア本部", "千葉エリア本部", "埼玉エリア本部",
    "北陸エリア本部", "甲信越エリア本部", "東海エリア本部", "名古屋エリア本部",
    "近畿エリア本部", "大阪エリア本部", "京都エリア本部", "神戸エリア本部",
    "中国エリア本部", "四国エリア本部", "九州エリア本部", "沖縄エリア本部",
    "営業統括本部", "法人営業本部", "リテール営業本部", "デジタル営業本部",
    "プロダクト開発本部", "システム開発本部", "インフラ基盤本部", "DX推進本部",
    "AI・データ本部", "品質管理本部",
    "人事本部", "総務本部", "経理財務本部", "法務本部", "コンプライアンス本部",
    "経営企画本部", "広報・IR本部", "新規事業本部",
    "カスタマーサクセス本部", "マーケティング本部",
    "物流本部", "購買本部", "製造本部", "研究開発本部",
    "海外事業本部", "グローバル人材本部", "情報セキュリティ本部", "内部監査本部",
]

SUB_DEPT_TEMPLATES = [
    "{area}支店", "{area}営業所", "{area}オフィス",
    "第一{func}課", "第二{func}課", "第三{func}課",
    "{func}推進室", "{func}企画室", "{func}管理室",
    "{func}第一グループ", "{func}第二グループ",
    "{func}センター", "{func}チーム",
]

FUNC_NAMES = [
    "営業", "開発", "企画", "管理", "人事", "経理", "法務", "品質",
    "カスタマー", "マーケ", "物流", "システム", "インフラ", "データ",
]

AREA_NAMES = [
    "札幌", "仙台", "盛岡", "秋田", "山形", "福島", "水戸", "宇都宮", "前橋",
    "さいたま", "千葉", "横浜", "川崎", "相模原",
    "新宿", "渋谷", "池袋", "品川", "丸の内", "銀座", "六本木", "上野", "秋葉原",
    "新潟", "富山", "金沢", "福井", "甲府", "長野", "松本",
    "静岡", "浜松", "名古屋", "岐阜", "四日市",
    "大阪", "京都", "神戸", "奈良", "和歌山", "堺",
    "岡山", "広島", "山口", "松山", "高松", "徳島", "高知",
    "福岡", "北九州", "長崎", "熊本", "大分", "宮崎", "鹿児島", "那覇",
]

GRADES = ["E1", "D1", "D2", "M1", "M2", "S1", "S2", "J1", "J2", "J3"]
GRADE_TITLES = {
    "E1": ["取締役", "執行役員"],
    "D1": ["本部長", "事業部長", "統括部長"],
    "D2": ["部長", "副部長", "担当部長"],
    "M1": ["課長", "室長", "センター長"],
    "M2": ["課長代理", "主幹", "グループリーダー"],
    "S1": ["主任", "係長", "チームリーダー"],
    "S2": ["副主任", "上級専門職"],
    "J1": ["一般社員(上級)", "専門職"],
    "J2": ["一般社員(中級)", "社員"],
    "J3": ["一般社員(初級)", "アシスタント", "新入社員"],
}

GRADE_SALARY_RANGE = {
    "E1": (14000000, 22000000), "D1": (11000000, 16000000), "D2": (9000000, 13000000),
    "M1": (7500000, 10500000), "M2": (6500000, 9000000), "S1": (5500000, 7500000),
    "S2": (4800000, 6500000), "J1": (4200000, 5500000), "J2": (3500000, 4800000),
    "J3": (2800000, 4000000),
}

GRADE_DIST_PER_DEPT = {
    "E1": 0, "D1": 1, "D2": 2, "M1": 3, "M2": 5,
    "S1": 10, "S2": 12, "J1": 15, "J2": 18, "J3": 14,
}

EVAL_PERIODS = ["2024-H1", "2024-H2", "2025-H1", "2025-H2"]
EVAL_GRADES = ["S", "A", "B", "C", "D"]
EVAL_GRADE_DIST = [0.05, 0.20, 0.50, 0.20, 0.05]

NOTE_CATEGORIES = ["career", "motivation", "concern", "performance", "other"]
NOTE_TEMPLATES = {
    "career": [
        "今後のキャリアについて話し合った。{name}は{topic}に興味を示している。",
        "{name}はスキルアップのため{topic}の研修を希望している。",
        "異動の希望について確認。{topic}分野への異動を検討中。",
    ],
    "motivation": [
        "モチベーションは高く、{topic}のプロジェクトに積極的に取り組んでいる。",
        "最近{topic}に対する意欲が見られる。引き続きサポートしていく。",
        "チーム内での{topic}への貢献が目立つ。",
    ],
    "concern": [
        "残業時間が増加傾向。{topic}の業務負荷を確認する必要あり。",
        "{topic}に関する不安を相談された。フォローアップが必要。",
        "体調面で少し心配な様子。{topic}の調整を検討。",
    ],
    "performance": [
        "{topic}の進捗は順調。期待以上のアウトプットを出している。",
        "前期と比べ{topic}のスキルが向上している。",
        "{topic}プロジェクトでリーダーシップを発揮している。",
    ],
    "other": [
        "定期面談実施。全体的に順調。{topic}について情報共有。",
        "社内イベントへの参加意向を確認。{topic}に関心あり。",
        "勤怠状況は良好。{topic}の件で軽く話し合い。",
    ],
}
NOTE_TOPICS = [
    "データ分析", "マネジメント", "新規プロジェクト", "クライアント対応",
    "チームビルディング", "技術研修", "組織改編", "業務効率化",
    "リモートワーク", "メンタルヘルス", "後輩育成", "資格取得",
]

EVAL_COMMENTS = [
    "業務遂行能力が高く、安定したパフォーマンスを発揮している。",
    "チーム内でのコミュニケーション能力が優れている。",
    "期待以上の成果を上げ、組織に大きく貢献した。",
    "自主的に業務改善に取り組む姿勢が評価できる。",
    "技術力の向上が著しく、難易度の高い案件も対応可能になった。",
    "リーダーシップを発揮し、チームの目標達成に貢献した。",
    "コミュニケーションスキルの改善が見られる。引き続き期待。",
    "業務の正確性は高いが、スピード面での改善が望まれる。",
    "後輩の指導に積極的に取り組んでいる。",
    "プロジェクトの計画立案能力が向上している。",
    "顧客からの信頼が厚く、対外的な評価も高い。",
    "新しい技術の習得に意欲的で、チームの技術力向上に貢献。",
]

ADDITIONAL_SKILLS = [
    ("React", "technical"), ("TypeScript", "technical"), ("Go", "technical"),
    ("Kubernetes", "technical"), ("Docker", "technical"), ("Terraform", "technical"),
    ("Rust", "technical"), ("C++", "technical"), ("Swift", "technical"),
    ("Tableau", "technical"), ("Excel VBA", "technical"),
    ("コーチング", "management"), ("ファシリテーション", "management"),
    ("韓国語", "language"), ("フランス語", "language"),
]


def gen_email(first, last, emp_code):
    return f"{emp_code.lower()}@hr-demo.example.com"


def gen_phone():
    return f"090-{random.randint(1000,9999)}-{random.randint(1000,9999)}"


def gen_birth_date(age_bucket):
    today = date(2026, 3, 16)
    if age_bucket == "20s":
        age = random.randint(22, 29)
    elif age_bucket == "30s":
        age = random.randint(30, 39)
    elif age_bucket == "40s":
        age = random.randint(40, 49)
    elif age_bucket == "50s":
        age = random.randint(50, 59)
    else:
        age = random.randint(60, 65)
    return today - timedelta(days=age * 365 + random.randint(0, 364))


def gen_hire_date(birth_date):
    age_at_hire = random.randint(22, 35)
    d = date(birth_date.year + age_at_hire, random.randint(1, 12), random.randint(1, 28))
    if d > date(2026, 3, 16):
        d = date(2025, 4, 1)
    return d


def main():
    conn = psycopg2.connect(**CONN_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()

    print("=== データ生成開始 ===")

    # ---- TRUNCATE existing data (reverse FK order) ----
    print("既存データクリア中...")
    cur.execute("SET search_path = hr")
    for tbl in [
        "chain_simulation_steps", "chain_simulations",
        "whatif_scenario_actions", "whatif_scenarios",
        "career_history", "agent_threads",
        "transfer_requests", "one_on_one_notes", "leave_records",
        "evaluations", "employee_skills", "candidate_lists", "action_items",
        "simulation_sessions",
    ]:
        cur.execute(f"TRUNCATE TABLE hr.{tbl} CASCADE")

    cur.execute("UPDATE hr.app_users SET employee_id = NULL")
    cur.execute("UPDATE hr.employees SET manager_id = NULL")
    cur.execute("TRUNCATE TABLE hr.employees CASCADE")
    cur.execute("TRUNCATE TABLE hr.positions CASCADE")
    cur.execute("TRUNCATE TABLE hr.departments CASCADE")
    cur.execute("TRUNCATE TABLE hr.skills CASCADE")
    conn.commit()

    # ---- Reset sequences ----
    for seq_tbl in ["departments_dept_id", "employees_employee_id", "positions_position_id",
                     "evaluations_evaluation_id", "skills_skill_id", "employee_skills_id",
                     "one_on_one_notes_note_id", "transfer_requests_request_id"]:
        cur.execute(f"ALTER SEQUENCE hr.{seq_tbl}_seq RESTART WITH 1")
    conn.commit()

    # ========== 1. DEPARTMENTS (191) ==========
    print("DEPARTMENTS 生成中...")
    dept_rows = []
    dept_id = 1

    # Level 0: CEO
    dept_rows.append((dept_id, "代表執行役社長", "CEO", None, 0, True))
    ceo_id = dept_id
    dept_id += 1

    # Level 1: 48 本部
    level1_ids = []
    for i, honbu_name in enumerate(AREA_HONBU):
        code = f"HQ{i+1:03d}"
        dept_rows.append((dept_id, honbu_name, code, ceo_id, 1, True))
        level1_ids.append((dept_id, honbu_name))
        dept_id += 1

    # Level 2: ~142 sub-departments
    level2_ids = []
    target_level2 = 142
    sub_per_honbu = target_level2 // len(level1_ids)
    remainder = target_level2 % len(level1_ids)

    used_codes = set()
    for idx, (parent_id, parent_name) in enumerate(level1_ids):
        n_subs = sub_per_honbu + (1 if idx < remainder else 0)
        for j in range(n_subs):
            area = random.choice(AREA_NAMES)
            func = random.choice(FUNC_NAMES)
            tmpl = random.choice(SUB_DEPT_TEMPLATES)
            sub_name = tmpl.format(area=area, func=func)
            code = f"D{dept_id:04d}"
            while code in used_codes:
                code = f"D{random.randint(1000,9999)}"
            used_codes.add(code)
            dept_rows.append((dept_id, sub_name, code, parent_id, 2, True))
            level2_ids.append((dept_id, sub_name, parent_id))
            dept_id += 1

    execute_values(cur,
        "INSERT INTO hr.departments (dept_id, dept_name, dept_code, parent_dept_id, level, is_active) VALUES %s",
        dept_rows
    )
    cur.execute(f"ALTER SEQUENCE hr.departments_dept_id_seq RESTART WITH {dept_id}")
    conn.commit()
    print(f"  DEPARTMENTS: {len(dept_rows)} 件")

    all_dept_ids = [r[0] for r in dept_rows]
    leaf_dept_ids = [r[0] for r in level2_ids]
    honbu_dept_ids = [r[0] for r in level1_ids]

    # ========== 2. SKILLS (30) ==========
    print("SKILLS 生成中...")
    skill_rows = [
        ("Python", "technical"), ("SQL", "technical"), ("Java", "technical"),
        ("JavaScript", "technical"), ("AWS", "technical"),
        ("プロジェクト管理", "management"), ("チームマネジメント", "management"),
        ("営業戦略", "management"), ("英語", "language"), ("中国語", "language"),
        ("TOEIC 800+", "certification"), ("PMP", "certification"),
        ("簿記2級", "certification"), ("データ分析", "technical"), ("機械学習", "technical"),
    ] + ADDITIONAL_SKILLS

    skill_ids = []
    for sname, scat in skill_rows:
        cur.execute("INSERT INTO hr.skills (skill_name, category) VALUES (%s, %s) RETURNING skill_id", (sname, scat))
        skill_ids.append(cur.fetchone()[0])
    conn.commit()
    print(f"  SKILLS: {len(skill_ids)} 件")

    # ========== 3. POSITIONS (~1,195) ==========
    print("POSITIONS 生成中...")
    position_rows = []
    pos_id = 1
    dept_positions = {}

    for dept_id_val, dept_name, parent_id in level2_ids:
        dept_positions[dept_id_val] = {}
        for grade in GRADES:
            titles = GRADE_TITLES[grade]
            n = max(1, GRADE_DIST_PER_DEPT.get(grade, 1) // 5)
            for _ in range(n):
                title = random.choice(titles)
                is_vacant = random.random() < 0.05
                headcount = random.choice([1, 1, 1, 2]) if grade in ("J2", "J3", "J1") else 1
                position_rows.append((pos_id, title, dept_id_val, grade, is_vacant, headcount))
                if grade not in dept_positions[dept_id_val]:
                    dept_positions[dept_id_val][grade] = []
                dept_positions[dept_id_val][grade].append(pos_id)
                pos_id += 1

    # positions for honbu-level departments (D1/D2/M1 only)
    for hid, hname in level1_ids:
        dept_positions[hid] = {}
        for grade in ["D1", "D2", "M1"]:
            titles = GRADE_TITLES[grade]
            title = random.choice(titles)
            position_rows.append((pos_id, title, hid, grade, False, 1))
            dept_positions[hid][grade] = [pos_id]
            pos_id += 1

    # CEO position
    position_rows.append((pos_id, "代表執行役社長", ceo_id, "E1", False, 1))
    dept_positions[ceo_id] = {"E1": [pos_id]}
    pos_id += 1

    execute_values(cur,
        "INSERT INTO hr.positions (position_id, title, dept_id, grade, is_vacant, headcount) VALUES %s",
        position_rows
    )
    cur.execute(f"ALTER SEQUENCE hr.positions_position_id_seq RESTART WITH {pos_id}")
    conn.commit()
    print(f"  POSITIONS: {len(position_rows)} 件")

    # ========== 4. EMPLOYEES (15,213) ==========
    print("EMPLOYEES 生成中... (15,213件)")
    TARGET_ACTIVE = 14071
    TARGET_INACTIVE = 1142
    TARGET_TOTAL = TARGET_ACTIVE + TARGET_INACTIVE

    # age distribution: 20s:10%, 30s:20%, 40s:25%, 50s:30%, 60s:15%
    age_buckets = (
        ["20s"] * int(TARGET_TOTAL * 0.10) +
        ["30s"] * int(TARGET_TOTAL * 0.20) +
        ["40s"] * int(TARGET_TOTAL * 0.25) +
        ["50s"] * int(TARGET_TOTAL * 0.30) +
        ["60s"] * int(TARGET_TOTAL * 0.15)
    )
    while len(age_buckets) < TARGET_TOTAL:
        age_buckets.append(random.choice(["30s", "40s", "50s"]))
    random.shuffle(age_buckets)

    # distribute employees across leaf departments
    emp_per_dept = {}
    remaining = TARGET_TOTAL
    for i, (did, _, _) in enumerate(level2_ids):
        if i == len(level2_ids) - 1:
            emp_per_dept[did] = remaining
        else:
            n = max(20, int(TARGET_TOTAL / len(level2_ids) * random.uniform(0.5, 1.5)))
            n = min(n, remaining - (len(level2_ids) - i - 1) * 10)
            emp_per_dept[did] = n
            remaining -= n

    employee_rows = []
    emp_id = 1
    emp_idx = 0
    dept_employees = {}
    dept_managers = {}

    for dept_id_val in leaf_dept_ids:
        n_emps = emp_per_dept.get(dept_id_val, 50)
        dept_employees[dept_id_val] = []
        first_in_dept = True

        for _ in range(n_emps):
            if emp_idx >= len(age_buckets):
                break
            bucket = age_buckets[emp_idx]
            gender = "M" if random.random() < 0.55 else "F"
            last = random.choice(LAST_NAMES)
            first = random.choice(FIRST_NAMES_M if gender == "M" else FIRST_NAMES_F)
            emp_code = f"EMP{emp_id:06d}"
            email = gen_email(first, last, emp_code)
            phone = gen_phone()
            birth = gen_birth_date(bucket)
            hire = gen_hire_date(birth)
            status = "active"
            if emp_id > TARGET_ACTIVE:
                status = random.choice(["retired", "leave", "inactive"])

            # assign grade based on age/tenure
            tenure_years = (date(2026, 3, 16) - hire).days / 365
            if bucket == "60s" and tenure_years > 25:
                grade = random.choice(["E1", "D1", "D2"])
            elif bucket == "50s" and tenure_years > 15:
                grade = random.choices(["D1", "D2", "M1", "M2"], weights=[0.1, 0.2, 0.3, 0.4])[0]
            elif bucket == "40s":
                grade = random.choices(["D2", "M1", "M2", "S1"], weights=[0.1, 0.2, 0.3, 0.4])[0]
            elif bucket == "30s":
                grade = random.choices(["M2", "S1", "S2", "J1"], weights=[0.1, 0.2, 0.3, 0.4])[0]
            else:
                grade = random.choices(["J1", "J2", "J3"], weights=[0.2, 0.4, 0.4])[0]

            positions_for_grade = dept_positions.get(dept_id_val, {}).get(grade, [])
            if not positions_for_grade:
                for fallback_grade in GRADES:
                    positions_for_grade = dept_positions.get(dept_id_val, {}).get(fallback_grade, [])
                    if positions_for_grade:
                        grade = fallback_grade
                        break
            position_id = random.choice(positions_for_grade) if positions_for_grade else None

            sal_low, sal_high = GRADE_SALARY_RANGE.get(grade, (3000000, 5000000))
            salary = random.randint(sal_low // 10000, sal_high // 10000) * 10000

            emp_type = random.choices(["正社員", "契約社員", "パート"], weights=[0.85, 0.10, 0.05])[0]
            commute = random.randint(10, 90) if random.random() < 0.8 else None
            promo_date = None
            if tenure_years > 3 and random.random() < 0.4:
                promo_date = hire + timedelta(days=int(tenure_years * 365 * random.uniform(0.3, 0.8)))

            manager_id = dept_managers.get(dept_id_val)

            employee_rows.append((
                emp_id, emp_code, first, last, email, phone,
                hire, birth, gender, dept_id_val, position_id, manager_id,
                status, salary, emp_type, commute, promo_date,
            ))

            dept_employees[dept_id_val].append(emp_id)
            if first_in_dept and grade in ("D1", "D2", "M1"):
                dept_managers[dept_id_val] = emp_id
                first_in_dept = False

            emp_id += 1
            emp_idx += 1

    # insert in batches
    BATCH = 2000
    for i in range(0, len(employee_rows), BATCH):
        batch = employee_rows[i:i+BATCH]
        execute_values(cur,
            """INSERT INTO hr.employees
            (employee_id, employee_code, first_name, last_name, email, phone,
             hire_date, birth_date, gender, dept_id, position_id, manager_id,
             status, salary, employment_type, commute_time_minutes, last_promotion_date)
            VALUES %s""",
            batch
        )
        conn.commit()
        if (i // BATCH) % 5 == 0:
            print(f"  ... {min(i+BATCH, len(employee_rows))}/{len(employee_rows)}")

    cur.execute(f"ALTER SEQUENCE hr.employees_employee_id_seq RESTART WITH {emp_id}")
    conn.commit()
    total_emps = len(employee_rows)
    print(f"  EMPLOYEES: {total_emps} 件")

    # 入社区分（新卒/中途）。乱数の並びを変えないよう、社員IDから決める
    cur.execute("""UPDATE hr.employees
        SET entry_type = CASE WHEN employee_id % 2 = 0 THEN 'new_grad' ELSE 'mid_career' END""")
    conn.commit()

    # update managers for those that didn't have one
    print("  マネージャー割当中...")
    for dept_id_val, emps in dept_employees.items():
        if len(emps) > 1 and dept_managers.get(dept_id_val):
            mgr = dept_managers[dept_id_val]
            cur.execute(
                "UPDATE hr.employees SET manager_id = %s WHERE dept_id = %s AND employee_id != %s AND manager_id IS NULL",
                (mgr, dept_id_val, mgr)
            )
    conn.commit()

    # update app_users employee_id
    cur.execute("UPDATE hr.app_users SET employee_id = 10 WHERE username = 'admin'")
    cur.execute("UPDATE hr.app_users SET employee_id = 6 WHERE username = 'manager'")
    cur.execute("UPDATE hr.app_users SET employee_id = 18 WHERE username = 'viewer'")
    conn.commit()

    all_active_emp_ids = [r[0] for r in employee_rows if r[12] == "active"]
    all_emp_ids = [r[0] for r in employee_rows]

    # ========== 5. EVALUATIONS (~42,410) ==========
    print("EVALUATIONS 生成中...")
    eval_rows = []
    eval_id = 1
    for eid in all_active_emp_ids:
        n_periods = random.choices([4, 3, 2, 1], weights=[0.5, 0.25, 0.15, 0.10])[0]
        periods = random.sample(EVAL_PERIODS, n_periods)
        manager_id = random.choice(all_active_emp_ids[:1000])
        for period in periods:
            score = round(random.gauss(3.3, 0.8), 1)
            score = max(1.0, min(5.0, score))
            grade = random.choices(EVAL_GRADES, weights=EVAL_GRADE_DIST)[0]
            comment = random.choice(EVAL_COMMENTS)
            self_comment = random.choice(EVAL_COMMENTS) if random.random() < 0.6 else None
            self_score = round(random.gauss(3.5, 0.7), 1) if random.random() < 0.5 else None
            if self_score:
                self_score = max(1.0, min(5.0, self_score))
            status = random.choices(["completed", "draft", "submitted"], weights=[0.7, 0.15, 0.15])[0]
            eval_rows.append((eval_id, eid, manager_id, period, score, grade, comment, self_comment, self_score, status))
            eval_id += 1

    for i in range(0, len(eval_rows), BATCH):
        batch = eval_rows[i:i+BATCH]
        execute_values(cur,
            """INSERT INTO hr.evaluations
            (evaluation_id, employee_id, evaluator_id, period, score, grade, comment, self_comment, self_score, status)
            VALUES %s""",
            batch
        )
        conn.commit()
        if (i // BATCH) % 5 == 0:
            print(f"  ... {min(i+BATCH, len(eval_rows))}/{len(eval_rows)}")

    cur.execute(f"ALTER SEQUENCE hr.evaluations_evaluation_id_seq RESTART WITH {eval_id}")
    conn.commit()
    print(f"  EVALUATIONS: {len(eval_rows)} 件")

    # ========== 6. EMPLOYEE_SKILLS (~53,251) ==========
    print("EMPLOYEE_SKILLS 生成中...")
    es_rows = []
    es_id = 1
    for eid in all_active_emp_ids:
        n_skills = random.choices([2, 3, 4, 5, 6], weights=[0.1, 0.25, 0.35, 0.2, 0.1])[0]
        chosen = random.sample(skill_ids, min(n_skills, len(skill_ids)))
        for sid in chosen:
            prof = random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.15, 0.35, 0.30, 0.15])[0]
            es_rows.append((es_id, eid, sid, prof))
            es_id += 1

    for i in range(0, len(es_rows), BATCH):
        batch = es_rows[i:i+BATCH]
        execute_values(cur,
            "INSERT INTO hr.employee_skills (id, employee_id, skill_id, proficiency) VALUES %s",
            batch
        )
        conn.commit()
        if (i // BATCH) % 5 == 0:
            print(f"  ... {min(i+BATCH, len(es_rows))}/{len(es_rows)}")

    cur.execute(f"ALTER SEQUENCE hr.employee_skills_id_seq RESTART WITH {es_id}")
    conn.commit()
    print(f"  EMPLOYEE_SKILLS: {len(es_rows)} 件")

    # ========== 7. ONE_ON_ONE_NOTES (~35,201) ==========
    print("ONE_ON_ONE_NOTES 生成中...")
    note_rows = []
    note_id = 1
    for eid in all_active_emp_ids:
        n_notes = random.choices([1, 2, 3, 4], weights=[0.2, 0.4, 0.3, 0.1])[0]
        emp_row = employee_rows[eid - 1] if eid <= len(employee_rows) else None
        emp_name = f"{emp_row[3]}{emp_row[2]}" if emp_row else "社員"
        mgr_id = emp_row[11] if emp_row and emp_row[11] else random.choice(all_active_emp_ids[:500])
        for _ in range(n_notes):
            cat = random.choice(NOTE_CATEGORIES)
            topic = random.choice(NOTE_TOPICS)
            templates = NOTE_TEMPLATES[cat]
            content = random.choice(templates).format(name=emp_name, topic=topic)
            note_date = date(2026, 3, 16) - timedelta(days=random.randint(1, 365))
            is_private = random.random() < 0.1
            note_rows.append((note_id, eid, mgr_id, note_date, content, cat, is_private))
            note_id += 1

    for i in range(0, len(note_rows), BATCH):
        batch = note_rows[i:i+BATCH]
        execute_values(cur,
            "INSERT INTO hr.one_on_one_notes (note_id, employee_id, manager_id, note_date, content, category, is_private) VALUES %s",
            batch
        )
        conn.commit()
        if (i // BATCH) % 5 == 0:
            print(f"  ... {min(i+BATCH, len(note_rows))}/{len(note_rows)}")

    cur.execute(f"ALTER SEQUENCE hr.one_on_one_notes_note_id_seq RESTART WITH {note_id}")
    conn.commit()
    print(f"  ONE_ON_ONE_NOTES: {len(note_rows)} 件")

    # ========== 8. TRANSFER_REQUESTS (1,500) ==========
    print("TRANSFER_REQUESTS 生成中...")
    tr_rows = []
    tr_id = 1
    for _ in range(1500):
        eid = random.choice(all_active_emp_ids)
        emp_row = employee_rows[eid - 1] if eid <= len(employee_rows) else None
        from_dept = emp_row[9] if emp_row else random.choice(leaf_dept_ids)
        to_dept = random.choice(leaf_dept_ids)
        while to_dept == from_dept:
            to_dept = random.choice(leaf_dept_ids)
        reason = random.choice([
            "キャリアアップのため", "業務適性の観点から", "組織再編に伴う異動",
            "本人希望", "プロジェクト配属", "部門間ローテーション",
        ])
        status = random.choices(["pending", "approved", "rejected", "completed"], weights=[0.3, 0.3, 0.1, 0.3])[0]
        requested_by = eid
        approved_by = random.choice(all_active_emp_ids[:500]) if status in ("approved", "completed") else None
        requested_at = date(2026, 3, 16) - timedelta(days=random.randint(1, 730))
        resolved_at = requested_at + timedelta(days=random.randint(7, 60)) if status in ("approved", "rejected", "completed") else None
        tr_rows.append((tr_id, eid, from_dept, to_dept, None, None, reason, status, requested_by, approved_by, requested_at, resolved_at))
        tr_id += 1

    execute_values(cur,
        """INSERT INTO hr.transfer_requests
        (request_id, employee_id, from_dept_id, to_dept_id, from_position_id, to_position_id,
         reason, status, requested_by, approved_by, requested_at, resolved_at)
        VALUES %s""",
        tr_rows
    )
    cur.execute(f"ALTER SEQUENCE hr.transfer_requests_request_id_seq RESTART WITH {tr_id}")
    conn.commit()
    print(f"  TRANSFER_REQUESTS: {len(tr_rows)} 件")

    # ========== 9. UNIQUE constraint fix for evaluations ==========
    print("重複評価データの整理中...")
    cur.execute("""
        DELETE FROM hr.evaluations a USING hr.evaluations b
        WHERE a.evaluation_id > b.evaluation_id
        AND a.employee_id = b.employee_id AND a.period = b.period
    """)
    conn.commit()

    # ========== SUMMARY ==========
    print("\n=== 生成完了 ===")
    for tbl in ["departments", "employees", "positions", "evaluations",
                 "one_on_one_notes", "skills", "employee_skills", "transfer_requests", "app_users"]:
        cur.execute(f"SELECT COUNT(*) FROM hr.{tbl}")
        cnt = cur.fetchone()[0]
        print(f"  {tbl}: {cnt:,}")

    cur.close()
    conn.close()
    print("\n完了!")


if __name__ == "__main__":
    main()
