# Job Alert Radar

Most job platforms let you filter by title, location, and salary. None of them let you filter by **working language**. If you're looking for English or Chinese-environment roles in Tokyo, you're stuck manually screening hundreds of Japanese-only postings.

Job Alert Radar solves this. It scrapes LinkedIn and Indeed simultaneously, runs keyword-based language detection on every job description, and only surfaces roles that match your language preference — then alerts you the moment they appear.

## How it works

1. **Multi-platform scraping** — pulls RSS feeds from LinkedIn, Indeed US, and Indeed Japan in parallel
2. **Language detection** — scans job descriptions for signals like "English required", "business English", "中文", "bilingual", and filters out Japanese-only roles automatically
3. **Real-time alerts** — emails you immediately when a matching job is posted, with deduplication so you never see the same role twice
4. **Daily digest** — sends a summary at a time you choose, collecting everything found throughout the day
5. **Company page monitor** — watches specific careers pages for any content changes, alerting you when a company you care about starts hiring

## Features

- Simultaneous scan across LinkedIn + Indeed (US and Japan)
- Multi-select working language filter: English, Chinese, Japanese, or any combination
- Instant **Scan Now** mode with results in the browser
- Background **Monitor** mode with configurable check interval
- Daily digest at a custom time of your choice
- Company careers page change detection
- MD5-based deduplication — no duplicate alerts
- Flask backend with multithreaded monitoring loops
- No API keys required to run

## Stack

Python · Flask · feedparser · threading · smtplib · HTML/CSS/JS

## Setup

```bash
git clone https://github.com/xhqi01/job-alert-radar.git
cd job-alert-radar
pip install -r requirements.txt
python app.py
```

Open [http://localhost:5000](http://localhost:5000).

## Deploy to Render (runs 24/7 for free)

1. Push to GitHub
2. [render.com](https://render.com) → New → **Web Service**
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `python app.py`
5. Add environment variables from `.env.example`
6. Deploy

## Notes

- RSS feeds carry a 15–30 minute delay from time of posting
- Language detection is keyword-based and covers the majority of cases
- Not affiliated with LinkedIn, Indeed, or any job platform
