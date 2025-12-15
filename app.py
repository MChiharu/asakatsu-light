import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, request, url_for, render_template_string
from openpyxl import load_workbook

import psycopg2


# =========================
# Timezone (JST)
# =========================
JST = ZoneInfo("Asia/Tokyo")

def jst_now():
    return datetime.now(JST)

def jst_today():
    return jst_now().date()


# =========================
# Quiz (Excel)
# =========================
QUIZ_XLSX_PATH = "quiz_database.xlsx"   # リポジトリ直下
QUIZ_SHEET_NAME = "quiz"               # テンプレ通り

def load_quiz_bank_from_excel(path: str = QUIZ_XLSX_PATH, sheet_name: str = QUIZ_SHEET_NAME):
    """
    Excelから問題を読み込み、内部形式に変換する。
    必須列: id, question, choice1, choice2, choice3, choice4, answer
    任意列: category, explanation
    answer は 1〜4（人間に優しい）を想定し、内部では 0〜3 に変換する。
    """
    wb = load_workbook(path, data_only=True)

    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Sheet '{sheet_name}' not found in {path}. Found: {wb.sheetnames}")

    ws = wb[sheet_name]

    # 1行目: ヘッダ
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    headers = [str(v).strip() if v is not None else "" for v in header_row]
    col = {h: i for i, h in enumerate(headers)}

    required = ["id", "question", "choice1", "choice2", "choice3", "choice4", "answer"]
    missing = [h for h in required if h not in col]
    if missing:
        raise ValueError(f"Missing required columns in Excel header: {missing}. Header={headers}")

    quiz_bank = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row:
            continue

        q = row[col["question"]] if col["question"] < len(row) else None
        if q is None or str(q).strip() == "":
            continue

        choices = []
        for key in ["choice1", "choice2", "choice3", "choice4"]:
            v = row[col[key]] if col[key] < len(row) else ""
            choices.append("" if v is None else str(v))

        ans_raw = row[col["answer"]] if col["answer"] < len(row) else None
        try:
            ans = int(str(ans_raw).strip())
        except Exception:
            continue

        if not (1 <= ans <= 4):
            continue

        cat = ""
        if "category" in col and col["category"] < len(row) and row[col["category"]] is not None:
            cat = str(row[col["category"]]).strip()

        exp = ""
        if "explanation" in col and col["explanation"] < len(row) and row[col["explanation"]] is not None:
            exp = str(row[col["explanation"]]).strip()

        quiz_bank.append({
            "question": str(q).strip(),
            "choices": choices,
            "answer_index": ans - 1,  # 0〜3
            "category": cat,
            "explanation": exp,
        })

    if not quiz_bank:
        raise ValueError("No valid quizzes loaded from Excel (all rows invalid or empty).")

    return quiz_bank


def get_today_quiz(quiz_bank):
    today = jst_today()
    key = today.year * 10000 + today.month * 100 + today.day
    idx = key % len(quiz_bank)
    return quiz_bank[idx]


# =========================
# Database (PostgreSQL via Render)
# =========================
def get_db_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (Render Environment Variables)")

    # Render等で必要になることがあるのでSSL要求を付与
    if "sslmode=" not in url:
        joiner = "&" if "?" in url else "?"
        url = url + f"{joiner}sslmode=require"

    return psycopg2.connect(url)


def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wakeups (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            ts TEXT NOT NULL,
            day TEXT NOT NULL
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


# =========================
# Flask app
# =========================
app = Flask(__name__)

# 起動時に一度だけ準備
QUIZ_BANK = load_quiz_bank_from_excel()
init_db()


# =========================
# HTML templates
# =========================
INDEX_HTML = """
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>朝活ログイン</title></head>
  <body>
    <h1>朝活ログイン</h1>
    <p style="color:gray;">（現在の問題数：{{ quiz_count }}問）</p>
    <p>内定者限定・日替わりITクイズでログイン 🤖</p>

    {% if error %}
      <p style="color:red;">{{ error }}</p>
    {% endif %}

    <form method="post">
      <p>名前： <input type="text" name="name" required></p>

      <hr>
      <h2>今日のクイズ</h2>
      {% if quiz_category %}
        <p style="color:gray;">カテゴリ：{{ quiz_category }}</p>
      {% endif %}
      <p>{{ quiz_question }}</p>

      {% for choice in quiz_choices %}
        <label>
          <input type="radio" name="choice" value="{{ loop.index0 }}">
          {{ choice }}
        </label><br>
      {% endfor %}

      <p><button type="submit">起きた！ログインする</button></p>
    </form>

    <hr>
    <p><a href="{{ url_for('today') }}">今日のみんなの起床時間を見る</a></p>
    <p><a href="{{ url_for('history') }}">起床履歴（ヒストリー）を見る</a></p>
  </body>
</html>
"""

RESULT_HTML = """
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>判定</title></head>
  <body>
    <h1>{{ title }}</h1>
    <p>{{ message }}</p>

    {% if ok %}
      {% if explanation %}
        <hr>
        <p><b>解説</b></p>
        <p>{{ explanation }}</p>
      {% endif %}
      <p><a href="{{ url_for('today') }}">今日のみんなの起床時間へ</a></p>
      <script>
        setTimeout(() => { window.location.href = "{{ url_for('today') }}"; }, 1200);
      </script>
    {% else %}
      <p><a href="{{ url_for('index') }}">ログイン画面に戻る</a></p>
    {% endif %}
  </body>
</html>
"""

TODAY_HTML = """
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>今日の起床時間</title></head>
  <body>
    <h1>今日の起床時間</h1>
    <p>日付: {{ today_str }}</p>

    {% if rows %}
      <table border="1" cellpadding="4">
        <tr><th>名前</th><th>起きた時間</th></tr>
        {% for name, ts in rows %}
          <tr><td>{{ name }}</td><td>{{ ts }}</td></tr>
        {% endfor %}
      </table>
    {% else %}
      <p>まだ誰も起きていません…？</p>
    {% endif %}

    <p><a href="{{ url_for('index') }}">ログインページに戻る</a></p>
    <p><a href="{{ url_for('history') }}">起床履歴を見る</a></p>
  </body>
</html>
"""

HISTORY_HTML = """
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>起床履歴</title></head>
  <body>
    <h1>起床履歴（ヒストリー）</h1>
    <p>表示期間: {{ start_str }} 〜 {{ end_str }}</p>

    {% if rows_by_day %}
      {% for day, items in rows_by_day %}
        <h2>{{ day }}</h2>
        <ul>
          {% for name, ts in items %}
            <li>{{ ts }} - {{ name }}</li>
          {% endfor %}
        </ul>
      {% endfor %}
    {% else %}
      <p>まだ履歴がありません。</p>
    {% endif %}

    <hr>
    <p><a href="{{ url_for('index') }}">ログインページに戻る</a></p>
    <p><a href="{{ url_for('today') }}">今日の起床時間を見る</a></p>
  </body>
</html>
"""


# =========================
# Routes
# =========================
@app.route("/", methods=["GET", "POST"])
def index():
    quiz = get_today_quiz(QUIZ_BANK)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        choice_idx_str = request.form.get("choice")

        if not name:
            return render_template_string(
                INDEX_HTML,
                error="名前を入力してください。",
                quiz_question=quiz["question"],
                quiz_choices=quiz["choices"],
                quiz_category=quiz.get("category", ""),
                quiz_count=len(QUIZ_BANK),
            )

        if choice_idx_str is None:
            return render_template_string(
                INDEX_HTML,
                error="クイズの選択肢を選んでください。",
                quiz_question=quiz["question"],
                quiz_choices=quiz["choices"],
                quiz_category=quiz.get("category", ""),
                quiz_count=len(QUIZ_BANK),
            )

        try:
            choice_idx = int(choice_idx_str)
        except ValueError:
            return render_template_string(
                INDEX_HTML,
                error="選択肢が不正です。",
                quiz_question=quiz["question"],
                quiz_choices=quiz["choices"],
                quiz_category=quiz.get("category", ""),
                quiz_count=len(QUIZ_BANK),
            )

        if choice_idx != quiz["answer_index"]:
            return render_template_string(
                RESULT_HTML,
                ok=False,
                title="❌ 不正解！",
                message="もう一度考えてみよう！",
                explanation=None,
            )

        # 正解 → 起床時間を記録（JST）
        now = jst_now()
        ts_str = now.strftime("%H:%M:%S")
        day_str = now.strftime("%Y-%m-%d")

        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO wakeups (name, ts, day) VALUES (%s, %s, %s)",
            (name, ts_str, day_str),
        )
        conn.commit()
        cur.close()
        conn.close()

        return render_template_string(
            RESULT_HTML,
            ok=True,
            title="✅ ログイン成功！",
            message=f"{name} さんの起床時間（{ts_str}）を記録しました。",
            explanation=quiz.get("explanation") or None,
        )

    # GET
    return render_template_string(
        INDEX_HTML,
        error=None,
        quiz_question=quiz["question"],
        quiz_choices=quiz["choices"],
        quiz_category=quiz.get("category", ""),
        quiz_count=len(QUIZ_BANK),
    )


@app.route("/today")
def today():
    today_str = jst_today().strftime("%Y-%m-%d")

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT name, ts FROM wakeups WHERE day = %s ORDER BY ts ASC",
        (today_str,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return render_template_string(TODAY_HTML, today_str=today_str, rows=rows)


@app.route("/history")
def history():
    N_DAYS_HISTORY = 30  # 好きに変更OK（例：30日表示）

    end_date = jst_today()
    start_date = end_date - timedelta(days=N_DAYS_HISTORY - 1)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT day, name, ts
        FROM wakeups
        WHERE day BETWEEN %s AND %s
        ORDER BY day DESC, ts ASC
    """, (start_str, end_str))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    rows_by_day_dict = {}
    for day_str, name, ts in rows:
        rows_by_day_dict.setdefault(day_str, []).append((name, ts))

    rows_by_day = sorted(rows_by_day_dict.items(), key=lambda x: x[0], reverse=True)

    return render_template_string(
        HISTORY_HTML,
        rows_by_day=rows_by_day,
        start_str=start_str,
        end_str=end_str,
    )


# （確認用：必要なときだけ使って、動いたら消してOK）
@app.route("/admin/dbinfo")
def admin_dbinfo():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(day), MAX(day) FROM wakeups")
    count, minday, maxday = cur.fetchone()
    cur.close()
    conn.close()
    return {"count": count, "min_day": minday, "max_day": maxday}


if __name__ == "__main__":
    # ローカル起動用。Renderではgunicornが起動するのでここは使われません
    app.run(host="0.0.0.0", port=5000, debug=True)
