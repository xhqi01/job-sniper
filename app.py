import os
import re
import time
import hashlib
import smtplib
import threading
import feedparser
import requests
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder=".")

# ── STATE ─────────────────────────────────────────────────────────────────────
seen_jobs      = set()
daily_digest   = []          # jobs collected today for 18:00 digest
company_hashes = {}          # url -> last content hash for company page monitoring

# ── RSS SOURCES ───────────────────────────────────────────────────────────────
def build_rss_urls(keywords, location):
    kw  = "+".join(keywords.split())
    loc = "+".join(location.split())
    return {
        "LinkedIn":  f"https://www.linkedin.com/jobs/search?keywords={kw}&location={loc}&f_TPR=r86400&format=rss",
        "Indeed":    f"https://www.indeed.com/rss?q={kw}&l={loc}&sort=date",
        "Indeed JP": f"https://jp.indeed.com/rss?q={kw}&l={loc}&sort=date",
    }

# ── LANGUAGE DETECTION ────────────────────────────────────────────────────────
def detect_language_hints(text):
    text_lower = text.lower()
    english_signals = [
        "english", "english required", "english proficiency", "business english",
        "native english", "fluent english", "english speaker", "english environment",
        "working language: english", "english-speaking", "global team",
        "international team", "english preferred",
    ]
    chinese_signals = [
        "chinese", "mandarin", "中文", "普通话", "chinese speaker",
        "chinese required", "chinese proficiency", "business chinese",
        "bilingual", "chinese environment",
    ]
    japanese_only_signals = [
        "日本語のみ", "japanese only", "japanese native", "ネイティブレベル",
        "日本語必須", "日本語ビジネスレベル",
    ]
    en_score = sum(1 for s in english_signals if s in text_lower)
    zh_score = sum(1 for s in chinese_signals if s in text_lower)
    jp_only  = any(s in text_lower for s in japanese_only_signals)
    return {
        "english": en_score > 0, "chinese": zh_score > 0,
        "japanese_only": jp_only, "en_score": en_score, "zh_score": zh_score,
    }

def matches_language_filter(text, title, lang_filter):
    if lang_filter == "any":
        return True
    combined = (text + " " + title).lower()
    hints    = detect_language_hints(combined)
    if lang_filter == "english":
        return hints["english"] and not hints["japanese_only"]
    elif lang_filter == "chinese":
        return hints["chinese"] and not hints["japanese_only"]
    elif lang_filter == "english_or_chinese":
        return (hints["english"] or hints["chinese"]) and not hints["japanese_only"]
    return True

# ── JOB FETCHING ──────────────────────────────────────────────────────────────
def fetch_jobs(keywords, location, lang_filter, max_per_source=10):
    rss_urls = build_rss_urls(keywords, location)
    new_jobs = []
    for source, url in rss_urls.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_source]:
                job_id = hashlib.md5((entry.get("link","") + entry.get("title","")).encode()).hexdigest()
                if job_id in seen_jobs:
                    continue
                title         = entry.get("title", "Untitled")
                link          = entry.get("link", "")
                summary       = entry.get("summary","") or entry.get("description","")
                summary_clean = re.sub(r'<[^>]+>',' ', summary).strip()
                published     = entry.get("published","")
                if not matches_language_filter(summary_clean, title, lang_filter):
                    continue
                hints     = detect_language_hints((summary_clean + " " + title).lower())
                lang_tags = []
                if hints["english"]: lang_tags.append("EN")
                if hints["chinese"]: lang_tags.append("ZH")
                if not lang_tags:    lang_tags.append("JP")
                new_jobs.append({
                    "id": job_id, "title": title, "source": source,
                    "link": link, "summary": summary_clean[:300],
                    "published": published, "lang_tags": lang_tags,
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
        except Exception as e:
            print(f"  ✗ {source}: {e}")
    return new_jobs

def mark_seen(jobs):
    for job in jobs:
        seen_jobs.add(job["id"])

# ── EMAIL BUILDER ─────────────────────────────────────────────────────────────
def build_job_cards(jobs):
    cards = ""
    for j in jobs:
        lang_html = "".join(
            f'<span style="background:#f0f0f0;padding:2px 8px;font-size:11px;margin-right:4px">{t}</span>'
            for t in j.get("lang_tags", [])
        )
        cards += f"""
        <div style="background:#fff;border:1px solid #e0e0e0;padding:16px;margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
            <a href="{j['link']}" style="color:#1a1a1a;text-decoration:none;font-weight:600;font-size:14px;line-height:1.4">{j['title']}</a>
            <span style="font-size:11px;color:#aaa;margin-left:12px;flex-shrink:0">{j.get('source','')}</span>
          </div>
          <div style="margin-bottom:8px">{lang_html}</div>
          {f'<div style="font-size:12px;color:#666;line-height:1.6">{j["summary"][:200]}…</div>' if j.get("summary") else ''}
          <div style="margin-top:10px">
            <a href="{j['link']}" style="color:#1a1a1a;font-size:12px;border-bottom:1px solid #ccc">View job →</a>
          </div>
        </div>"""
    return cards

def build_alert_email(jobs, keywords, location):
    return f"""
    <html><body style="font-family:monospace;background:#f7f6f3;padding:32px">
    <div style="max-width:600px;margin:0 auto">
      <h2 style="margin:0 0 4px;font-size:15px">💼 New Jobs Found</h2>
      <p style="color:#888;font-size:12px;margin:0 0 20px">
        {len(jobs)} new posting{"s" if len(jobs)>1 else ""} · {keywords} · {location} · {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
      {build_job_cards(jobs)}
      <p style="font-size:11px;color:#bbb;margin-top:16px">job-alert-radar</p>
    </div></body></html>"""

def build_digest_email(jobs, keywords, location):
    today = date.today().strftime("%B %d, %Y")
    return f"""
    <html><body style="font-family:monospace;background:#f7f6f3;padding:32px">
    <div style="max-width:600px;margin:0 auto">
      <h2 style="margin:0 0 4px;font-size:15px">📋 Daily Job Digest — {today}</h2>
      <p style="color:#888;font-size:12px;margin:0 0 20px">
        {len(jobs)} job{"s" if len(jobs)>1 else ""} found today · {keywords} · {location}
      </p>
      {build_job_cards(jobs) if jobs else '<p style="color:#aaa;font-size:13px">No new jobs found today.</p>'}
      <p style="font-size:11px;color:#bbb;margin-top:16px">job-alert-radar · daily digest at 18:00</p>
    </div></body></html>"""

def build_company_email(company_name, url, changes):
    return f"""
    <html><body style="font-family:monospace;background:#f7f6f3;padding:32px">
    <div style="max-width:600px;margin:0 auto">
      <h2 style="margin:0 0 4px;font-size:15px">🏢 Company Page Updated</h2>
      <p style="color:#888;font-size:12px;margin:0 0 20px">
        {company_name} · {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
      <div style="background:#fff;border:1px solid #e0e0e0;padding:16px;margin-bottom:12px">
        <div style="font-weight:600;margin-bottom:8px">{company_name}</div>
        <div style="font-size:12px;color:#666;margin-bottom:10px">The careers page has changed — new jobs may have been posted.</div>
        <a href="{url}" style="color:#1a1a1a;font-size:12px;border-bottom:1px solid #ccc">Check careers page →</a>
      </div>
      <p style="font-size:11px;color:#bbb;margin-top:16px">job-alert-radar · company monitor</p>
    </div></body></html>"""

def send_email(sender, password, receiver, subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, password)
        s.sendmail(sender, receiver, msg.as_string())

# ── COMPANY PAGE MONITOR ──────────────────────────────────────────────────────
def check_company_page(url):
    """Fetch page, return hash of text content."""
    try:
        res  = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        text = re.sub(r'<[^>]+>', ' ', res.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return hashlib.md5(text.encode()).hexdigest()
    except:
        return None

def company_monitor_loop(companies, email_sender, email_pass, email_recv, interval):
    """Monitor company pages for changes."""
    # Init hashes
    for c in companies:
        h = check_company_page(c["url"])
        if h:
            company_hashes[c["url"]] = h
            print(f"[company] initialized: {c['name']}")

    while True:
        time.sleep(interval)
        for c in companies:
            new_hash = check_company_page(c["url"])
            if not new_hash:
                continue
            old_hash = company_hashes.get(c["url"])
            if old_hash and new_hash != old_hash:
                print(f"[company] change detected: {c['name']}")
                body = build_company_email(c["name"], c["url"], None)
                try:
                    send_email(email_sender, email_pass, email_recv,
                               f"🏢 {c['name']} careers page updated", body)
                except Exception as e:
                    print(f"[company] email error: {e}")
            company_hashes[c["url"]] = new_hash

def daily_digest_loop(keywords, location, email_sender, email_pass, email_recv, digest_time="18:00"):
    """Send daily digest at user-specified time."""
    hour, minute = map(int, digest_time.split(":"))
    print(f"[digest] daily digest scheduler started · sending at {digest_time}")
    last_sent_date = None
    while True:
        now = datetime.now()
        if now.hour == hour and now.minute == minute and last_sent_date != date.today():
            print(f"[digest] sending daily digest: {len(daily_digest)} jobs")
            body = build_digest_email(list(daily_digest), keywords, location)
            try:
                send_email(email_sender, email_pass, email_recv,
                           f"📋 Daily Job Digest — {date.today().strftime('%b %d')} ({len(daily_digest)} jobs)",
                           body)
                daily_digest.clear()
                last_sent_date = date.today()
            except Exception as e:
                print(f"[digest] email error: {e}")
        time.sleep(60)

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/scan", methods=["POST"])
def scan():
    data        = request.json
    keywords    = data.get("keywords","").strip()
    location    = data.get("location","Tokyo").strip()
    lang_filter = data.get("lang_filter","any")
    mark        = data.get("mark_seen", False)
    if not keywords:
        return jsonify({"error": "Please enter job keywords."}), 400
    try:
        jobs = fetch_jobs(keywords, location, lang_filter)
        if mark:
            mark_seen(jobs)
        return jsonify({"jobs": jobs, "total": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/notify", methods=["POST"])
def notify():
    data          = request.json
    keywords      = data.get("keywords","").strip()
    location      = data.get("location","Tokyo").strip()
    lang_filter   = data.get("lang_filter","any")
    email_sender  = data.get("email_sender","").strip()
    email_pass    = data.get("email_password","").strip()
    email_recv    = data.get("email_receiver","").strip()
    interval      = int(data.get("interval", 3600))
    digest        = data.get("daily_digest", False)

    digest_time   = data.get("digest_time", "18:00")

    if not all([keywords, email_sender, email_pass, email_recv]):
        return jsonify({"error": "Missing required fields."}), 400

    def monitor_loop():
        print(f"[monitor] started · {keywords} · {location} · every {interval}s")
        while True:
            try:
                jobs = fetch_jobs(keywords, location, lang_filter)
                if jobs:
                    mark_seen(jobs)
                    daily_digest.extend(jobs)  # add to daily digest pool
                    subject = f"💼 {len(jobs)} new job{'s' if len(jobs)>1 else ''}: {keywords}"
                    body    = build_alert_email(jobs, keywords, location)
                    send_email(email_sender, email_pass, email_recv, subject, body)
                    print(f"[monitor] sent alert: {len(jobs)} jobs")
                else:
                    print("[monitor] no new jobs")
            except Exception as e:
                print(f"[monitor] error: {e}")
            time.sleep(interval)

    threading.Thread(target=monitor_loop, daemon=True).start()

    if digest:
        threading.Thread(
            target=daily_digest_loop,
            args=(keywords, location, email_sender, email_pass, email_recv, digest_time),
            daemon=True
        ).start()

    return jsonify({"ok": True, "message": f"Monitoring started. Checking every {interval//60} min. {'Daily digest at 18:00 enabled.' if digest else ''}"})

@app.route("/api/company-monitor", methods=["POST"])
def company_monitor():
    data         = request.json
    companies    = data.get("companies", [])   # [{name, url}, ...]
    email_sender = data.get("email_sender","").strip()
    email_pass   = data.get("email_password","").strip()
    email_recv   = data.get("email_receiver","").strip()
    interval     = int(data.get("interval", 3600))

    if not companies:
        return jsonify({"error": "Add at least one company."}), 400
    if not all([email_sender, email_pass, email_recv]):
        return jsonify({"error": "Email credentials required."}), 400

    threading.Thread(
        target=company_monitor_loop,
        args=(companies, email_sender, email_pass, email_recv, interval),
        daemon=True
    ).start()

    return jsonify({"ok": True, "message": f"Monitoring {len(companies)} company page{'s' if len(companies)>1 else ''}."})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
