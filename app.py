from flask import Flask, request, redirect, url_for, render_template_string
import sqlite3
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

def jst_today():
    return datetime.now(JST).date()



DB_PATH = "wakeups.db"

app = Flask(__name__)

# ------------------------
# DB 初期化
# ------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS wakeups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ts TEXT NOT NULL,
            day TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

# Flask 3 でも確実に動くように、起動時に一回だけ初期化
init_db()

# ------------------------
# 日替わり IT クイズ（基本情報“風”の自作問題）
# ※ 過去問の本文をコピペすると著作権的に危ないので雰囲気寄せ
# ------------------------
QUIZ_BANK = [
    {"question": "2進数 (1010)₂ を 10進数で表したものはどれ？",
     "choices": ["8", "9", "10", "12"], "answer_index": 2},
    {"question": "1バイトは何ビット？",
     "choices": ["4ビット", "8ビット", "16ビット", "32ビット"], "answer_index": 1},
    {"question": "OSの役割として適切なものはどれ？",
     "choices": ["HWとアプリの仲立ち", "ネット接続だけ", "文字入力だけ", "ソース自動生成"], "answer_index": 0},
    {"question": "LANの説明として最も適切なものはどれ？",
     "choices": ["世界中のネットワーク", "狭い範囲のネットワーク", "電話網のみ", "無線のみ"], "answer_index": 1},
    {"question": "情報セキュリティのCIAで C が意味するものはどれ？",
     "choices": ["Confidence", "Control", "Confidentiality", "Connection"], "answer_index": 2},
]

def get_today_quiz():
    today = jst_today()
    key = today.year * 10000 + today.month * 100 + today.day
    idx = key % len(QUIZ_BANK)
    return QUIZ_BANK[idx]

# ------------------------
# HTML（全部 triple-quote で閉じてる完成形）
# ------------------------
INDEX_HTML = """
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>朝活ログイン</title></head>
  <body>
    <h1>朝活ログイン</h1>
    <p>内定者限定・日替わりITクイズでログイン 🤖</p>

    {% if error %}
      <p style="color:red;">{{ error }}</p>
    {% endif %}

    <form method="post">
      <p>名前： <input type="text" name="name" required></p>

      <hr>
      <h2>今日のクイズ</h2>
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

# ------------------------
# Routes
# ------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    quiz = get_today_quiz()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        choice_idx_str = request.form.get("choice")

        if not name:
            return render_template_string(INDEX_HTML, error="名前を入力してください。",
                                          quiz_question=quiz["question"], quiz_choices=quiz["choices"])
        if choice_idx_str is None:
            return render_template_string(INDEX_HTML, error="クイズの選択肢を選んでください。",
                                          quiz_question=quiz["question"], quiz_choices=quiz["choices"])

        try:
            choice_idx = int(choice_idx_str)
        except ValueError:
            return render_template_string(INDEX_HTML, error="選択肢が不正です。",
                                          quiz_question=quiz["question"], quiz_choices=quiz["choices"])

        if choice_idx != quiz["answer_index"]:
            return render_template_string(RESULT_HTML, ok=False, title="❌ 不正解！",
                                          message="もう一度考えてみよう！")

        # 正解 → 記録
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        ts_str = now.strftime("%H:%M:%S")
        day_str = now.strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO wakeups (name, ts, day) VALUES (?, ?, ?)", (name, ts_str, day_str))
        conn.commit()
        conn.close()

        return render_template_string(RESULT_HTML, ok=True, title="✅ ログイン成功！",
                                      message=f"{name} さんの起床時間（{ts_str}）を記録しました。")

    return render_template_string(INDEX_HTML, error=None,
                                  quiz_question=quiz["question"], quiz_choices=quiz["choices"])

@app.route("/today")
def today():
    today_str = jst_today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, ts FROM wakeups WHERE day = ? ORDER BY ts ASC", (today_str,))
    rows = c.fetchall()
    conn.close()
    return render_template_string(TODAY_HTML, today_str=today_str, rows=rows)

@app.route("/history")
def history():
    N_DAYS_HISTORY = 7
    end_date = jst_today()
    start_date = end_date - timedelta(days=N_DAYS_HISTORY - 1)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT day, name, ts
        FROM wakeups
        WHERE day BETWEEN ? AND ?
        ORDER BY day DESC, ts ASC
    """, (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))
    rows = c.fetchall()
    conn.close()

    rows_by_day_dict = {}
    for day_str, name, ts in rows:
        rows_by_day_dict.setdefault(day_str, []).append((name, ts))

    rows_by_day = sorted(rows_by_day_dict.items(), key=lambda x: x[0], reverse=True)

    return render_template_string(HISTORY_HTML,
                                  rows_by_day=rows_by_day,
                                  start_str=start_date.strftime("%Y-%m-%d"),
                                  end_str=end_date.strftime("%Y-%m-%d"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

