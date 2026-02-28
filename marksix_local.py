#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH_DEFAULT = str(SCRIPT_DIR / "marksix_local.db")
CSV_PATH_DEFAULT = str(SCRIPT_DIR / "Mark_Six.csv")
OFFICIAL_URL_DEFAULT = "https://bet.hkjc.com/contentserver/jcbw/cmc/last30draw.json"
THIRD_PARTY_MAX_PAGES_DEFAULT = 60
THIRD_PARTY_URLS_DEFAULT: List[str] = [
    "https://lottolyzer.com/history/hong-kong/mark-six/page/1/per-page/50/summary-view",
]
MINED_CONFIG_KEY = "mined_strategy_config_v1"
ALL_NUMBERS = list(range(1, 50))
STRATEGY_LABELS = {
    "balanced_v1": "组合策略",
    "hot_v1": "热号策略",
    "cold_rebound_v1": "冷号回补",
    "momentum_v1": "近期动量",
    "ensemble_v2": "集成投票",
    "pattern_mined_v1": "规律挖掘",
}
STRATEGY_IDS = ["balanced_v1", "hot_v1", "cold_rebound_v1", "momentum_v1", "ensemble_v2", "pattern_mined_v1"]


@dataclass
class DrawRecord:
    issue_no: str
    draw_date: str
    numbers: List[int]
    special_number: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS draws (
            issue_no TEXT PRIMARY KEY,
            draw_date TEXT NOT NULL,
            numbers_json TEXT NOT NULL,
            special_number INTEGER NOT NULL,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prediction_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_no TEXT NOT NULL,
            strategy TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            hit_count INTEGER,
            hit_rate REAL,
            hit_count_10 INTEGER,
            hit_rate_10 REAL,
            hit_count_14 INTEGER,
            hit_rate_14 REAL,
            hit_count_20 INTEGER,
            hit_rate_20 REAL,
            special_hit INTEGER,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(issue_no, strategy)
        );

        CREATE TABLE IF NOT EXISTS prediction_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            pick_type TEXT NOT NULL DEFAULT 'MAIN',
            number INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            score REAL NOT NULL,
            reason TEXT NOT NULL,
            UNIQUE(run_id, number),
            FOREIGN KEY(run_id) REFERENCES prediction_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS prediction_pools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            pool_size INTEGER NOT NULL,
            numbers_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, pool_size),
            FOREIGN KEY(run_id) REFERENCES prediction_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS model_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    _ensure_migrations(conn)
    conn.commit()

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _ensure_migrations(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "prediction_picks", "pick_type"):
        conn.execute("ALTER TABLE prediction_picks ADD COLUMN pick_type TEXT NOT NULL DEFAULT 'MAIN'")
    if not _column_exists(conn, "prediction_runs", "special_hit"):
        conn.execute("ALTER TABLE prediction_runs ADD COLUMN special_hit INTEGER")
    if not _column_exists(conn, "prediction_runs", "hit_count_10"):
        conn.execute("ALTER TABLE prediction_runs ADD COLUMN hit_count_10 INTEGER")
    if not _column_exists(conn, "prediction_runs", "hit_rate_10"):
        conn.execute("ALTER TABLE prediction_runs ADD COLUMN hit_rate_10 REAL")
    if not _column_exists(conn, "prediction_runs", "hit_count_14"):
        conn.execute("ALTER TABLE prediction_runs ADD COLUMN hit_count_14 INTEGER")
    if not _column_exists(conn, "prediction_runs", "hit_rate_14"):
        conn.execute("ALTER TABLE prediction_runs ADD COLUMN hit_rate_14 REAL")
    if not _column_exists(conn, "prediction_runs", "hit_count_20"):
        conn.execute("ALTER TABLE prediction_runs ADD COLUMN hit_count_20 INTEGER")
    if not _column_exists(conn, "prediction_runs", "hit_rate_20"):
        conn.execute("ALTER TABLE prediction_runs ADD COLUMN hit_rate_20 REAL")


def get_model_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM model_state WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def set_model_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO model_state(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now),
    )


def _pick(row: Dict[str, str], keys: Sequence[str]) -> str:
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return ""


def _parse_date(date_text: str) -> Optional[str]:
    text = date_text.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_numbers(value: str) -> List[int]:
    out: List[int] = []
    for token in value.replace("，", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            n = int(token)
        except ValueError:
            continue
        if 1 <= n <= 49:
            out.append(n)
    return out


def parse_draw_csv(csv_path: str) -> List[DrawRecord]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    records: List[DrawRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
            issue_no = _pick(row, ["期号", "期數", "issueNo", "issue_no"])
            draw_date = _parse_date(_pick(row, ["日期", "date", "drawDate", "draw_date"]))
            special = _pick(row, ["特别号码", "特別號碼", "special", "specialNumber", "no7", "n7"])

            numbers = _parse_numbers(_pick(row, ["中奖号码", "中獎號碼", "numbers", "result"]))
            if len(numbers) != 6:
                split_keys = ["中奖号码 1", "中獎號碼 1", "1"], ["2"], ["3"], ["4"], ["5"], ["6"]
                split_nums: List[int] = []
                ok = True
                for key_group in split_keys:
                    value = _pick(row, list(key_group))
                    if not value:
                        ok = False
                        break
                    try:
                        n = int(value)
                    except ValueError:
                        ok = False
                        break
                    if not (1 <= n <= 49):
                        ok = False
                        break
                    split_nums.append(n)
                if ok:
                    numbers = split_nums

            try:
                special_n = int(special)
            except ValueError:
                continue

            if not issue_no or not draw_date:
                continue
            if len(numbers) != 6 or not (1 <= special_n <= 49):
                continue

            records.append(
                DrawRecord(
                    issue_no=issue_no,
                    draw_date=draw_date,
                    numbers=numbers,
                    special_number=special_n,
                )
            )

    records.sort(key=lambda r: (r.draw_date, r.issue_no))
    dedup: Dict[str, DrawRecord] = {}
    for r in records:
        dedup[r.issue_no] = r
    return sorted(dedup.values(), key=lambda r: (r.draw_date, r.issue_no))


def parse_draw_csv_text(csv_text: str) -> List[DrawRecord]:
    records: List[DrawRecord] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for raw in reader:
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        issue_no = _pick(row, ["期号", "期數", "issueNo", "issue_no"])
        draw_date = _parse_date(_pick(row, ["日期", "date", "drawDate", "draw_date"]))
        special = _pick(row, ["特别号码", "特別號碼", "special", "specialNumber", "no7", "n7"])

        numbers = _parse_numbers(_pick(row, ["中奖号码", "中獎號碼", "numbers", "result"]))
        if len(numbers) != 6:
            split_keys = ["中奖号码 1", "中獎號碼 1", "1"], ["2"], ["3"], ["4"], ["5"], ["6"]
            split_nums: List[int] = []
            ok = True
            for key_group in split_keys:
                value = _pick(row, list(key_group))
                if not value:
                    ok = False
                    break
                try:
                    n = int(value)
                except ValueError:
                    ok = False
                    break
                if not (1 <= n <= 49):
                    ok = False
                    break
                split_nums.append(n)
            if ok:
                numbers = split_nums

        try:
            special_n = int(special)
        except ValueError:
            continue

        if not issue_no or not draw_date:
            continue
        if len(numbers) != 6 or not (1 <= special_n <= 49):
            continue

        records.append(
            DrawRecord(
                issue_no=issue_no,
                draw_date=draw_date,
                numbers=numbers,
                special_number=special_n,
            )
        )

    records.sort(key=lambda r: (r.draw_date, r.issue_no))
    dedup: Dict[str, DrawRecord] = {}
    for r in records:
        dedup[r.issue_no] = r
    return sorted(dedup.values(), key=lambda r: (r.draw_date, r.issue_no))


def _to_int(value: object) -> Optional[int]:
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None
    return n if 1 <= n <= 49 else None


def _extract_issue_no(row: Dict[str, object]) -> str:
    for key in ("issueNo", "drawNo", "draw", "issue", "period", "id"):
        text = str(row.get(key, "")).strip()
        if text and "/" in text:
            return text
    return ""


def _extract_draw_date(row: Dict[str, object]) -> Optional[str]:
    for key in ("date", "drawDate", "draw_date", "drawdate", "dt"):
        value = row.get(key)
        if value is None:
            continue
        d = _parse_date(str(value))
        if d:
            return d
    return None


def _extract_main_numbers(row: Dict[str, object]) -> List[int]:
    split = []
    for key in ("n1", "n2", "n3", "n4", "n5", "n6", "no1", "no2", "no3", "no4", "no5", "no6"):
        if key in row:
            n = _to_int(row.get(key))
            if n is not None:
                split.append(n)
    if len(split) >= 6:
        return split[:6]

    for key in ("numbers", "nos", "no", "result", "main"):
        nums = _parse_numbers(str(row.get(key, "")))
        if len(nums) >= 6:
            return nums[:6]
    return []


def _extract_special_number(row: Dict[str, object]) -> Optional[int]:
    for key in ("specialNumber", "special", "sno", "sn", "bonus", "extra", "n7", "no7"):
        n = _to_int(row.get(key))
        if n is not None:
            return n
    for key in ("result", "no", "numbers"):
        nums = _parse_numbers(str(row.get(key, "")))
        if len(nums) >= 7:
            n = nums[6]
            return n if 1 <= n <= 49 else None
    return None


def parse_official_json(payload: object) -> List[DrawRecord]:
    rows: List[Dict[str, object]] = []
    if isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
    elif isinstance(payload, dict):
        for key in ("data", "results", "rows", "items", "draws", "list"):
            item = payload.get(key)
            if isinstance(item, list):
                rows = [r for r in item if isinstance(r, dict)]
                break

    out: List[DrawRecord] = []
    for row in rows:
        issue_no = _extract_issue_no(row)
        draw_date = _extract_draw_date(row)
        numbers = _extract_main_numbers(row)
        special = _extract_special_number(row)
        if not issue_no or not draw_date or len(numbers) != 6 or special is None:
            continue
        out.append(DrawRecord(issue_no=issue_no, draw_date=draw_date, numbers=numbers, special_number=special))

    dedup: Dict[str, DrawRecord] = {}
    for r in out:
        dedup[r.issue_no] = r
    return sorted(dedup.values(), key=lambda r: (r.draw_date, r.issue_no))


def fetch_official_records(official_url: str) -> List[DrawRecord]:
    req = Request(
        official_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; marksix-local/1.0)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8-sig")
    payload = json.loads(raw)
    records = parse_official_json(payload)
    if not records:
        raise RuntimeError("Official source parsed 0 records. Please check official URL format.")
    return records


def fetch_records_from_url(url: str, source_label: str, third_party_max_pages: int = THIRD_PARTY_MAX_PAGES_DEFAULT) -> List[DrawRecord]:
    if "lottolyzer.com/history/hong-kong/mark-six" in url:
        records = fetch_lottolyzer_records(url, max_pages=third_party_max_pages)
        if records:
            return records

    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; marksix-local/1.0)",
            "Accept": "application/json,text/plain,text/csv,*/*",
        },
    )
    with urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8-sig")

    stripped = raw.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        payload = json.loads(raw)
        records = parse_official_json(payload)
        if records:
            return records

    records = parse_draw_csv_text(raw)
    if records:
        return records

    raise RuntimeError(f"{source_label} parsed 0 records.")


def parse_lottolyzer_html(raw_html: str) -> List[DrawRecord]:
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)

    pattern = re.compile(
        r"(?P<issue>\d{2}/\d{3})\s+"
        r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
        r"(?P<numbers>\d{1,2}(?:,\d{1,2}){5})\s+"
        r"(?P<extra>\d{1,2})\b"
    )

    out: List[DrawRecord] = []
    for m in pattern.finditer(text):
        issue_no = m.group("issue").strip()
        draw_date = _parse_date(m.group("date").strip())
        numbers = _parse_numbers(m.group("numbers").strip())
        extra = _to_int(m.group("extra").strip())
        if not draw_date or len(numbers) != 6 or extra is None:
            continue
        out.append(DrawRecord(issue_no=issue_no, draw_date=draw_date, numbers=numbers, special_number=extra))

    dedup: Dict[str, DrawRecord] = {}
    for r in out:
        dedup[r.issue_no] = r
    return sorted(dedup.values(), key=lambda r: (r.draw_date, r.issue_no))


def _lottolyzer_total_pages(raw_html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = re.sub(r"\s+", " ", text)
    candidates = re.findall(r"\b\d+\s*/\s*(\d+)\b", text)
    if not candidates:
        return 1
    nums = [int(x) for x in candidates if x.isdigit()]
    nums = [n for n in nums if 1 <= n <= 300]
    return max(nums) if nums else 1


def _lottolyzer_page_url(base_url: str, page_no: int) -> str:
    if re.search(r"/page/\d+/", base_url):
        return re.sub(r"/page/\d+/", f"/page/{page_no}/", base_url)
    if base_url.endswith("/"):
        return f"{base_url}page/{page_no}/"
    return f"{base_url}/page/{page_no}/"


def fetch_lottolyzer_records(base_url: str, max_pages: int = 20) -> List[DrawRecord]:
    req = Request(
        base_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; marksix-local/1.0)",
            "Accept": "text/html,*/*",
        },
    )
    with urlopen(req, timeout=20) as resp:
        first_html = resp.read().decode("utf-8-sig")

    total_pages = _lottolyzer_total_pages(first_html)
    pages_to_fetch = max(1, min(total_pages, max_pages))
    all_records = parse_lottolyzer_html(first_html)

    for page_no in range(2, pages_to_fetch + 1):
        page_url = _lottolyzer_page_url(base_url, page_no)
        try:
            req2 = Request(
                page_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; marksix-local/1.0)",
                    "Accept": "text/html,*/*",
                },
            )
            with urlopen(req2, timeout=20) as resp2:
                html = resp2.read().decode("utf-8-sig")
            all_records.extend(parse_lottolyzer_html(html))
        except Exception:
            break

    dedup: Dict[str, DrawRecord] = {}
    for r in all_records:
        dedup[r.issue_no] = r
    return sorted(dedup.values(), key=lambda r: (r.draw_date, r.issue_no))


def fetch_online_records_with_fallback(official_url: str, third_party_url: str) -> Tuple[List[DrawRecord], str]:
    errors: List[str] = []
    if official_url.strip():
        try:
            return fetch_records_from_url(official_url, "official source"), "official_api"
        except Exception as exc:
            errors.append(f"official failed: {exc}")

    if third_party_url.strip():
        try:
            return fetch_records_from_url(third_party_url, "third-party source"), "third_party_api"
        except Exception as exc:
            errors.append(f"third-party failed: {exc}")

    raise RuntimeError(" | ".join(errors) if errors else "No online source configured.")


def parse_url_list(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        for part in value.split(","):
            url = part.strip()
            if url:
                out.append(url)
    dedup: List[str] = []
    seen = set()
    for u in out:
        if u not in seen:
            dedup.append(u)
            seen.add(u)
    return dedup


def fetch_online_records_with_multi_fallback(
    official_url: str,
    third_party_urls: Sequence[str],
    third_party_max_pages: int = THIRD_PARTY_MAX_PAGES_DEFAULT,
) -> Tuple[List[DrawRecord], str, str]:
    errors: List[str] = []
    if official_url.strip():
        try:
            records = fetch_records_from_url(official_url, "official source", third_party_max_pages=third_party_max_pages)
            return records, "official_api", official_url
        except Exception as exc:
            errors.append(f"official failed: {exc}")

    for idx, url in enumerate(third_party_urls):
        try:
            records = fetch_records_from_url(
                url,
                f"third-party source #{idx + 1}",
                third_party_max_pages=third_party_max_pages,
            )
            return records, f"third_party_api_{idx + 1}", url
        except Exception as exc:
            errors.append(f"third_party[{idx + 1}] failed: {exc}")

    raise RuntimeError(" | ".join(errors) if errors else "No online source configured.")


def upsert_draw(conn: sqlite3.Connection, record: DrawRecord, source: str) -> str:
    now = utc_now()
    existing = conn.execute("SELECT issue_no FROM draws WHERE issue_no = ?", (record.issue_no,)).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE draws
            SET draw_date = ?, numbers_json = ?, special_number = ?, source = ?, updated_at = ?
            WHERE issue_no = ?
            """,
            (record.draw_date, json.dumps(record.numbers), record.special_number, source, now, record.issue_no),
        )
        return "updated"
    conn.execute(
        """
        INSERT INTO draws(issue_no, draw_date, numbers_json, special_number, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (record.issue_no, record.draw_date, json.dumps(record.numbers), record.special_number, source, now, now),
    )
    return "inserted"


def sync_from_csv(conn: sqlite3.Connection, csv_path: str, source: str = "local_csv") -> Tuple[int, int, int]:
    records = parse_draw_csv(csv_path)
    return sync_from_records(conn, records, source)


def sync_from_records(conn: sqlite3.Connection, records: List[DrawRecord], source: str) -> Tuple[int, int, int]:
    inserted, updated = 0, 0
    for r in records:
        result = upsert_draw(conn, r, source)
        if result == "inserted":
            inserted += 1
        else:
            updated += 1
    conn.commit()
    return len(records), inserted, updated


def has_any_draw(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM draws LIMIT 1").fetchone()
    return row is not None


def parse_issue(issue_no: str) -> Optional[Tuple[str, int, int]]:
    parts = issue_no.split("/")
    if len(parts) != 2:
        return None
    year_s, seq_s = parts
    if not (year_s.isdigit() and seq_s.isdigit()):
        return None
    return year_s, int(seq_s), len(seq_s)


def issue_sort_key(issue_no: str) -> Optional[int]:
    parsed = parse_issue(issue_no)
    if not parsed:
        return None
    year_s, seq, _ = parsed
    return int(year_s) * 1000 + seq


def build_issue(year_s: str, seq: int, width: int) -> str:
    return f"{year_s}/{str(seq).zfill(width)}"


def next_issue(issue_no: str) -> str:
    parsed = parse_issue(issue_no)
    if not parsed:
        return issue_no
    year, seq, width = parsed
    return f"{year}/{str(seq + 1).zfill(width)}"


def missing_issues_since_latest(conn: sqlite3.Connection, incoming: List[DrawRecord]) -> List[str]:
    latest_row = conn.execute("SELECT issue_no FROM draws ORDER BY draw_date DESC, issue_no DESC LIMIT 1").fetchone()
    if not latest_row:
        return []

    latest_issue = str(latest_row["issue_no"])
    latest_parsed = parse_issue(latest_issue)
    latest_key = issue_sort_key(latest_issue)
    if not latest_parsed or latest_key is None:
        return []

    incoming_set = {r.issue_no for r in incoming}
    incoming_keys = [issue_sort_key(r.issue_no) for r in incoming if issue_sort_key(r.issue_no) is not None]
    if not incoming_keys:
        return []

    max_key = max(incoming_keys)
    if max_key <= latest_key:
        return []

    year_s, seq, width = latest_parsed
    missing: List[str] = []
    probe_key = latest_key
    probe_year = int(year_s)
    probe_seq = seq

    while probe_key < max_key:
        probe_seq += 1
        if probe_seq > 366:
            probe_year += 1
            probe_seq = 1
            width = 3
        issue = build_issue(str(probe_year).zfill(len(year_s)), probe_seq, width)
        probe_key = probe_year * 1000 + probe_seq
        if issue not in incoming_set:
            exists = conn.execute("SELECT 1 FROM draws WHERE issue_no = ? LIMIT 1", (issue,)).fetchone()
            if not exists:
                missing.append(issue)

    return missing


def load_recent_draws(conn: sqlite3.Connection, limit: int = 120) -> List[List[int]]:
    rows = conn.execute(
        "SELECT numbers_json FROM draws ORDER BY draw_date DESC, issue_no DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [json.loads(r["numbers_json"]) for r in rows]


def _normalize(score_map: Dict[int, float]) -> Dict[int, float]:
    values = list(score_map.values())
    mn, mx = min(values), max(values)
    if mx == mn:
        return {k: 0.0 for k in score_map}
    return {k: (v - mn) / (mx - mn) for k, v in score_map.items()}


def _freq_map(draws: List[List[int]]) -> Dict[int, float]:
    freq = {n: 0.0 for n in ALL_NUMBERS}
    for draw in draws:
        for n in draw:
            freq[n] += 1.0
    return freq


def _omission_map(draws: List[List[int]]) -> Dict[int, float]:
    omission = {n: float(len(draws) + 1) for n in ALL_NUMBERS}
    for i, draw in enumerate(draws):
        for n in draw:
            omission[n] = min(omission[n], float(i + 1))
    return omission


def _momentum_map(draws: List[List[int]]) -> Dict[int, float]:
    m = {n: 0.0 for n in ALL_NUMBERS}
    for i, draw in enumerate(draws):
        w = 1.0 / (1.0 + i)
        for n in draw:
            m[n] += w
    return m


def _pair_affinity_map(draws: List[List[int]], window: int = 200) -> Dict[int, float]:
    pair_count: Dict[Tuple[int, int], int] = {}
    for draw in draws[:window]:
        s = sorted(draw)
        for i in range(len(s)):
            for j in range(i + 1, len(s)):
                key = (s[i], s[j])
                pair_count[key] = pair_count.get(key, 0) + 1

    social = {n: 0.0 for n in ALL_NUMBERS}
    for (a, b), c in pair_count.items():
        social[a] += float(c)
        social[b] += float(c)
    return social


def _zone_heat_map(draws: List[List[int]], window: int = 80) -> Dict[int, float]:
    zone_counts = [0.0] * 5
    w = draws[:window]
    if not w:
        return {n: 0.0 for n in ALL_NUMBERS}
    for draw in w:
        for n in draw:
            zone = min(4, (n - 1) // 10)
            zone_counts[zone] += 1.0
    expected = 6.0 * len(w) / 5.0
    zone_score = [expected - c for c in zone_counts]
    return {n: zone_score[min(4, (n - 1) // 10)] for n in ALL_NUMBERS}


def _pick_top_six(scores: Dict[int, float], reason: str) -> List[Tuple[int, int, float, str]]:
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    picked: List[Tuple[int, float]] = []
    for n, s in ranked:
        if len(picked) == 6:
            break
        proposal = [pn for pn, _ in picked] + [n]
        odd_count = sum(1 for x in proposal if x % 2 == 1)
        if len(proposal) >= 4 and (odd_count == 0 or odd_count == len(proposal)):
            continue
        zone_counts: Dict[int, int] = {}
        for x in proposal:
            z = min(4, (x - 1) // 10)
            zone_counts[z] = zone_counts.get(z, 0) + 1
        if any(c >= 4 for c in zone_counts.values()):
            continue
        picked.append((n, s))
    while len(picked) < 6:
        for n, s in ranked:
            if n not in [pn for pn, _ in picked]:
                picked.append((n, s))
                break

    # Sum range adjustment: keep typical sum around history center.
    target_low, target_high = 95, 205
    top6 = [n for n, _ in picked[:6]]
    total = sum(top6)
    if not (target_low <= total <= target_high):
        for i in range(5, -1, -1):
            replaced = False
            for alt_n, alt_s in ranked:
                if alt_n in top6:
                    continue
                candidate = list(top6)
                candidate[i] = alt_n
                csum = sum(candidate)
                if target_low <= csum <= target_high:
                    picked[i] = (alt_n, alt_s)
                    top6 = candidate
                    replaced = True
                    break
            if replaced:
                break

    return [(n, idx + 1, s, f"{reason} score={s:.4f}") for idx, (n, s) in enumerate(picked)]


def _default_mined_config() -> Dict[str, float]:
    return {
        "window": 80.0,
        "w_freq": 0.40,
        "w_omit": 0.30,
        "w_mom": 0.20,
        "w_pair": 0.05,
        "w_zone": 0.05,
        "special_bonus": 0.10,
    }


def _candidate_mined_configs() -> List[Dict[str, float]]:
    windows = [40, 60, 80, 120, 160]
    weight_triplets = [
        (0.50, 0.30, 0.20),
        (0.45, 0.35, 0.20),
        (0.40, 0.40, 0.20),
        (0.35, 0.45, 0.20),
        (0.30, 0.50, 0.20),
        (0.60, 0.20, 0.20),
        (0.20, 0.60, 0.20),
        (0.40, 0.30, 0.30),
        (0.30, 0.40, 0.30),
    ]
    pair_zone_sets = [
        (0.00, 0.00),
        (0.05, 0.05),
        (0.10, 0.00),
        (0.00, 0.10),
    ]
    out: List[Dict[str, float]] = []
    for w in windows:
        for wf, wo, wm in weight_triplets:
            for wp, wz in pair_zone_sets:
                out.append(
                    {
                        "window": float(w),
                        "w_freq": wf,
                        "w_omit": wo,
                        "w_mom": wm,
                        "w_pair": wp,
                        "w_zone": wz,
                        "special_bonus": 0.10,
                    }
                )
    return out


def _apply_weight_config(
    draws: List[List[int]],
    config: Dict[str, float],
    reason: str,
) -> Tuple[List[Tuple[int, int, float, str]], int, float, Dict[int, float]]:
    window_size = int(config.get("window", 80))
    window = draws[: max(20, window_size)]
    freq = _normalize(_freq_map(window))
    omission = _normalize(_omission_map(window))
    momentum = _normalize(_momentum_map(window))
    pair = _normalize(_pair_affinity_map(window, window=min(200, len(window))))
    zone = _normalize(_zone_heat_map(window, window=min(80, len(window))))

    w_freq = float(config.get("w_freq", 0.45))
    w_omit = float(config.get("w_omit", 0.35))
    w_mom = float(config.get("w_mom", 0.20))
    w_pair = float(config.get("w_pair", 0.00))
    w_zone = float(config.get("w_zone", 0.00))

    scores: Dict[int, float] = {}
    for n in ALL_NUMBERS:
        scores[n] = (
            freq[n] * w_freq
            + omission[n] * w_omit
            + momentum[n] * w_mom
            + pair[n] * w_pair
            + zone[n] * w_zone
        )

    main_picks = _pick_top_six(scores, reason)
    main_set = {n for n, _, _, _ in main_picks}
    special_candidates = [(n, s) for n, s in sorted(scores.items(), key=lambda x: x[1], reverse=True) if n not in main_set]
    if not special_candidates:
        special_candidates = [(n, s) for n, s in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
    special_number, special_score = special_candidates[0]
    return main_picks, special_number, special_score, scores


def mine_pattern_config_from_rows(rows: Sequence[sqlite3.Row]) -> Dict[str, float]:
    if len(rows) < 120:
        return _default_mined_config()

    candidates = _candidate_mined_configs()
    best_cfg = _default_mined_config()
    best_score = -1.0

    min_history = 20
    eval_span = min(500, len(rows) - min_history)
    start = max(min_history, len(rows) - eval_span)

    parsed_main = [json.loads(r["numbers_json"]) for r in rows]
    parsed_special = [int(r["special_number"]) for r in rows]

    for cfg in candidates:
        score_sum = 0.0
        count = 0
        for i in range(start, len(rows)):
            hist_start = max(0, i - int(cfg["window"]))
            history_desc = [parsed_main[j] for j in range(i - 1, hist_start - 1, -1)]
            if len(history_desc) < min_history:
                continue
            picks, special, _, _ = _apply_weight_config(history_desc, cfg, "规律挖掘")
            picked_main = [n for n, _, _, _ in picks]
            win_main = set(parsed_main[i])
            hit_count = len([n for n in picked_main if n in win_main])
            special_hit = 1 if int(special) == parsed_special[i] else 0
            score_sum += hit_count / 6.0 + float(cfg.get("special_bonus", 0.10)) * special_hit
            count += 1

        if count == 0:
            continue
        score = score_sum / count
        if score > best_score:
            best_score = score
            best_cfg = cfg

    return best_cfg


def ensure_mined_pattern_config(conn: sqlite3.Connection, force: bool = False) -> Dict[str, float]:
    if not force:
        cached = get_model_state(conn, MINED_CONFIG_KEY)
        if cached:
            try:
                obj = json.loads(cached)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

    rows = _draws_ordered_asc(conn)
    cfg = mine_pattern_config_from_rows(rows)
    set_model_state(conn, MINED_CONFIG_KEY, json.dumps(cfg, ensure_ascii=False))
    conn.commit()
    return cfg


def _rank_vote_score(score_maps: Sequence[Dict[int, float]]) -> Dict[int, float]:
    votes = {n: 0.0 for n in ALL_NUMBERS}
    for m in score_maps:
        ranked = sorted(m.items(), key=lambda x: x[1], reverse=True)
        for rank, (n, _) in enumerate(ranked):
            votes[n] += float(49 - rank)
    return _normalize(votes)


def _build_candidate_pools(scores: Dict[int, float], main6: List[int]) -> Dict[int, List[int]]:
    ranked = [n for n, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
    main_unique = []
    for n in main6:
        if n not in main_unique:
            main_unique.append(n)

    rest = [n for n in ranked if n not in main_unique]
    pool10 = main_unique + rest[: max(0, 10 - len(main_unique))]
    pool14 = main_unique + rest[: max(0, 14 - len(main_unique))]
    pool20 = main_unique + rest[: max(0, 20 - len(main_unique))]
    return {6: main_unique[:6], 10: pool10[:10], 14: pool14[:14], 20: pool20[:20]}


def _pool_hit_count(pool_numbers: Sequence[int], winning: set[int]) -> int:
    return len([n for n in pool_numbers if n in winning])


def _save_prediction_pools(conn: sqlite3.Connection, run_id: int, pools: Dict[int, List[int]]) -> None:
    conn.execute("DELETE FROM prediction_pools WHERE run_id = ?", (run_id,))
    now = utc_now()
    for pool_size, numbers in pools.items():
        conn.execute(
            """
            INSERT INTO prediction_pools(run_id, pool_size, numbers_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, int(pool_size), json.dumps(numbers), now),
        )


def get_pool_numbers_for_run(conn: sqlite3.Connection, run_id: int, pool_size: int = 6) -> List[int]:
    row = conn.execute(
        "SELECT numbers_json FROM prediction_pools WHERE run_id = ? AND pool_size = ?",
        (run_id, int(pool_size)),
    ).fetchone()
    if not row:
        return []
    try:
        nums = json.loads(row["numbers_json"])
    except Exception:
        return []
    return [int(n) for n in nums if isinstance(n, (int, float)) or str(n).isdigit()]


def _ensemble_strategy(
    draws: List[List[int]],
    mined_cfg: Optional[Dict[str, float]],
) -> Tuple[List[Tuple[int, int, float, str]], int, float, Dict[int, float]]:
    m_hot = _apply_weight_config(draws, {"window": 80.0, "w_freq": 0.8, "w_omit": 0.0, "w_mom": 0.2}, "热号策略")
    m_cold = _apply_weight_config(draws, {"window": 80.0, "w_freq": 0.0, "w_omit": 0.7, "w_mom": 0.3}, "冷号回补")
    m_mom = _apply_weight_config(draws, {"window": 80.0, "w_freq": 0.1, "w_omit": 0.0, "w_mom": 0.9}, "近期动量")
    m_bal = _apply_weight_config(
        draws,
        {"window": 80.0, "w_freq": 0.4, "w_omit": 0.3, "w_mom": 0.2, "w_pair": 0.05, "w_zone": 0.05},
        "组合策略",
    )
    m_mined = _apply_weight_config(draws, mined_cfg or _default_mined_config(), "规律挖掘")

    score_maps = [m_hot[3], m_cold[3], m_mom[3], m_bal[3], m_mined[3]]

    voted = _rank_vote_score(score_maps)
    picked = _pick_top_six(voted, "集成投票")
    main_set = {n for n, _, _, _ in picked}
    candidates = [(n, s) for n, s in sorted(voted.items(), key=lambda x: x[1], reverse=True) if n not in main_set]
    if not candidates:
        candidates = sorted(voted.items(), key=lambda x: x[1], reverse=True)
    special_number, special_score = candidates[0]
    return picked, special_number, special_score, voted


def generate_strategy(
    draws: List[List[int]],
    strategy: str,
    mined_config: Optional[Dict[str, float]] = None,
) -> Tuple[List[Tuple[int, int, float, str]], int, float, Dict[int, float]]:
    if strategy == "hot_v1":
        return _apply_weight_config(draws, {"window": 80.0, "w_freq": 0.8, "w_omit": 0.0, "w_mom": 0.2}, "热号策略")
    if strategy == "cold_rebound_v1":
        return _apply_weight_config(draws, {"window": 80.0, "w_freq": 0.0, "w_omit": 0.7, "w_mom": 0.3}, "冷号回补")
    if strategy == "momentum_v1":
        return _apply_weight_config(draws, {"window": 80.0, "w_freq": 0.1, "w_omit": 0.0, "w_mom": 0.9}, "近期动量")
    if strategy == "ensemble_v2":
        return _ensemble_strategy(draws, mined_config)
    if strategy == "pattern_mined_v1":
        cfg = mined_config or _default_mined_config()
        return _apply_weight_config(draws, cfg, "规律挖掘")
    return _apply_weight_config(
        draws,
        {"window": 80.0, "w_freq": 0.40, "w_omit": 0.30, "w_mom": 0.20, "w_pair": 0.05, "w_zone": 0.05},
        "组合策略",
    )


def generate_predictions(conn: sqlite3.Connection, issue_no: Optional[str] = None) -> str:
    row = conn.execute("SELECT issue_no FROM draws ORDER BY draw_date DESC, issue_no DESC LIMIT 1").fetchone()
    if not row:
        raise RuntimeError("No draws found. Run sync/bootstrap first.")
    target_issue = issue_no or next_issue(row["issue_no"])
    draws = load_recent_draws(conn, 200)
    if len(draws) < 20:
        raise RuntimeError("Need at least 20 draws to generate predictions.")
    mined_cfg = ensure_mined_pattern_config(conn, force=False)

    for strategy in STRATEGY_IDS:
        now = utc_now()
        existing = conn.execute(
            "SELECT id FROM prediction_runs WHERE issue_no = ? AND strategy = ?",
            (target_issue, strategy),
        ).fetchone()
        if existing:
            run_id = existing["id"]
            conn.execute(
                """
                UPDATE prediction_runs
                SET status='PENDING', hit_count=NULL, hit_rate=NULL,
                    hit_count_10=NULL, hit_rate_10=NULL,
                    hit_count_14=NULL, hit_rate_14=NULL,
                    hit_count_20=NULL, hit_rate_20=NULL,
                    special_hit=NULL, reviewed_at=NULL, created_at=?
                WHERE id=?
                """,
                (now, run_id),
            )
            conn.execute("DELETE FROM prediction_picks WHERE run_id = ?", (run_id,))
        else:
            cur = conn.execute(
                """
                INSERT INTO prediction_runs(issue_no, strategy, status, created_at)
                VALUES (?, ?, 'PENDING', ?)
                """,
                (target_issue, strategy, now),
            )
            run_id = cur.lastrowid

        picks, special_number, special_score, score_map = generate_strategy(draws, strategy, mined_config=mined_cfg)
        main_numbers = [n for n, _, _, _ in picks]
        conn.executemany(
            """
            INSERT INTO prediction_picks(run_id, pick_type, number, rank, score, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(run_id, "MAIN", n, rank, score, reason) for n, rank, score, reason in picks]
            + [(run_id, "SPECIAL", special_number, 1, special_score, "特别号候选")],
        )
        # Build 6/10/14/20 pools from the strategy score ordering.
        # Use pick scores as primary signal and fill with remaining numbers by score rank.
        pools = _build_candidate_pools(score_map, main_numbers)
        _save_prediction_pools(conn, int(run_id), pools)
    conn.commit()
    return target_issue


def _draws_ordered_asc(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT issue_no, draw_date, numbers_json, special_number FROM draws ORDER BY draw_date ASC, issue_no ASC"
    ).fetchall()


def run_historical_backtest(
    conn: sqlite3.Connection,
    min_history: int = 20,
    rebuild: bool = False,
    progress_every: int = 20,
) -> Tuple[int, int]:
    draws = _draws_ordered_asc(conn)
    if len(draws) <= min_history:
        return 0, 0

    if rebuild:
        conn.execute(
            """
            DELETE FROM prediction_pools
            WHERE run_id IN (SELECT id FROM prediction_runs WHERE issue_no IN (SELECT issue_no FROM draws))
            """
        )
        conn.execute(
            """
            DELETE FROM prediction_runs
            WHERE issue_no IN (SELECT issue_no FROM draws)
            """
        )
        conn.commit()

    issues_processed = 0
    runs_processed = 0
    total_targets = len(draws) - min_history
    started_at = time.time()

    mined_cfg_cache: Dict[int, Dict[str, float]] = {}
    print(
        f"[backtest] start: total_issues={total_targets}, strategies_per_issue={len(STRATEGY_IDS)}, rebuild={rebuild}",
        flush=True,
    )

    for i in range(min_history, len(draws)):
        target = draws[i]
        issue_no = str(target["issue_no"])
        existing = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM prediction_runs
            WHERE issue_no = ? AND status = 'REVIEWED'
            """,
            (issue_no,),
        ).fetchone()
        if existing and int(existing["c"]) >= len(STRATEGY_IDS):
            continue

        history_desc = [json.loads(draws[j]["numbers_json"]) for j in range(i - 1, -1, -1)]
        winning_main = set(json.loads(target["numbers_json"]))
        winning_special = int(target["special_number"])

        for strategy in STRATEGY_IDS:
            mined_cfg = None
            if strategy == "pattern_mined_v1":
                # Refit mined config every 50 issues to avoid using future information.
                bucket = i // 50
                if bucket not in mined_cfg_cache:
                    mined_cfg_cache[bucket] = mine_pattern_config_from_rows(draws[:i])
                mined_cfg = mined_cfg_cache[bucket]
            main_picks, special_number, special_score, score_map = generate_strategy(
                history_desc,
                strategy,
                mined_config=mined_cfg,
            )
            picked_main = [n for n, _, _, _ in main_picks]
            pools = _build_candidate_pools(score_map, picked_main)
            hit_count = len([n for n in picked_main if n in winning_main])
            hit_rate = round(hit_count / 6.0, 4)
            hit_count_10 = _pool_hit_count(pools[10], winning_main)
            hit_count_14 = _pool_hit_count(pools[14], winning_main)
            hit_count_20 = _pool_hit_count(pools[20], winning_main)
            hit_rate_10 = round(hit_count_10 / 6.0, 4)
            hit_rate_14 = round(hit_count_14 / 6.0, 4)
            hit_rate_20 = round(hit_count_20 / 6.0, 4)
            special_hit = 1 if special_number == winning_special else 0

            now = utc_now()
            row = conn.execute(
                "SELECT id FROM prediction_runs WHERE issue_no = ? AND strategy = ?",
                (issue_no, strategy),
            ).fetchone()
            if row:
                run_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE prediction_runs
                    SET status='REVIEWED', hit_count=?, hit_rate=?,
                        hit_count_10=?, hit_rate_10=?,
                        hit_count_14=?, hit_rate_14=?,
                        hit_count_20=?, hit_rate_20=?,
                        special_hit=?, created_at=?, reviewed_at=?
                    WHERE id=?
                    """,
                    (
                        hit_count,
                        hit_rate,
                        hit_count_10,
                        hit_rate_10,
                        hit_count_14,
                        hit_rate_14,
                        hit_count_20,
                        hit_rate_20,
                        special_hit,
                        now,
                        now,
                        run_id,
                    ),
                )
                conn.execute("DELETE FROM prediction_picks WHERE run_id = ?", (run_id,))
            else:
                cur = conn.execute(
                    """
                    INSERT INTO prediction_runs(
                      issue_no, strategy, status, hit_count, hit_rate,
                      hit_count_10, hit_rate_10, hit_count_14, hit_rate_14, hit_count_20, hit_rate_20,
                      special_hit, created_at, reviewed_at
                    )
                    VALUES (?, ?, 'REVIEWED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        issue_no,
                        strategy,
                        hit_count,
                        hit_rate,
                        hit_count_10,
                        hit_rate_10,
                        hit_count_14,
                        hit_rate_14,
                        hit_count_20,
                        hit_rate_20,
                        special_hit,
                        now,
                        now,
                    ),
                )
                run_id = int(cur.lastrowid)

            conn.executemany(
                """
                INSERT INTO prediction_picks(run_id, pick_type, number, rank, score, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(run_id, "MAIN", n, rank, score, reason) for n, rank, score, reason in main_picks]
                + [(run_id, "SPECIAL", special_number, 1, special_score, "特别号候选")],
            )
            _save_prediction_pools(conn, run_id, pools)
            runs_processed += 1

        issues_processed += 1
        if (
            issues_processed == 1
            or issues_processed == total_targets
            or (progress_every > 0 and issues_processed % progress_every == 0)
        ):
            elapsed = max(time.time() - started_at, 1e-9)
            pct = (issues_processed / total_targets) * 100.0 if total_targets > 0 else 100.0
            speed = issues_processed / elapsed
            eta = ((total_targets - issues_processed) / speed) if speed > 0 else 0.0
            print(
                f"[backtest] progress: {issues_processed}/{total_targets} ({pct:.1f}%), "
                f"runs={runs_processed}, elapsed={elapsed:.0f}s, eta={eta:.0f}s",
                flush=True,
            )

    conn.commit()
    return issues_processed, runs_processed


def review_issue(conn: sqlite3.Connection, issue_no: str) -> int:
    draw = conn.execute("SELECT numbers_json, special_number FROM draws WHERE issue_no = ?", (issue_no,)).fetchone()
    if not draw:
        return 0
    winning = set(json.loads(draw["numbers_json"]))
    winning_special = int(draw["special_number"])
    runs = conn.execute(
        "SELECT id FROM prediction_runs WHERE issue_no = ? AND status = 'PENDING'",
        (issue_no,),
    ).fetchall()
    count = 0
    for run in runs:
        run_id = run["id"]
        picks = conn.execute(
            "SELECT pick_type, number FROM prediction_picks WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        main_picked = [p["number"] for p in picks if p["pick_type"] in (None, "MAIN")]
        special_picked = [p["number"] for p in picks if p["pick_type"] == "SPECIAL"]
        pool10 = get_pool_numbers_for_run(conn, int(run_id), 10) or main_picked
        pool14 = get_pool_numbers_for_run(conn, int(run_id), 14) or main_picked
        pool20 = get_pool_numbers_for_run(conn, int(run_id), 20) or main_picked
        hit_count = len([n for n in main_picked if n in winning])
        hit_rate = round(hit_count / 6.0, 4)
        hit_count_10 = _pool_hit_count(pool10, winning)
        hit_count_14 = _pool_hit_count(pool14, winning)
        hit_count_20 = _pool_hit_count(pool20, winning)
        hit_rate_10 = round(hit_count_10 / 6.0, 4)
        hit_rate_14 = round(hit_count_14 / 6.0, 4)
        hit_rate_20 = round(hit_count_20 / 6.0, 4)
        special_hit = 1 if (special_picked and special_picked[0] == winning_special) else 0
        conn.execute(
            """
            UPDATE prediction_runs
            SET status='REVIEWED', hit_count=?, hit_rate=?,
                hit_count_10=?, hit_rate_10=?,
                hit_count_14=?, hit_rate_14=?,
                hit_count_20=?, hit_rate_20=?,
                special_hit=?, reviewed_at=?
            WHERE id=?
            """,
            (
                hit_count,
                hit_rate,
                hit_count_10,
                hit_rate_10,
                hit_count_14,
                hit_rate_14,
                hit_count_20,
                hit_rate_20,
                special_hit,
                utc_now(),
                run_id,
            ),
        )
        count += 1
    conn.commit()
    return count


def review_latest(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT issue_no FROM draws ORDER BY draw_date DESC, issue_no DESC LIMIT 1").fetchone()
    if not row:
        return 0
    return review_issue(conn, row["issue_no"])


def _fmt_num(n: int) -> str:
    return str(n).zfill(2)


def get_latest_draw(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT issue_no, draw_date, numbers_json, special_number FROM draws ORDER BY draw_date DESC, issue_no DESC LIMIT 1"
    ).fetchone()


def get_pending_runs(conn: sqlite3.Connection, limit: int = 12) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT id, issue_no, strategy, created_at FROM prediction_runs WHERE status='PENDING' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


def get_review_stats(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          strategy,
          COUNT(*) AS c,
          AVG(hit_count) AS avg_hit,
          AVG(hit_rate) AS avg_rate,
          AVG(hit_count_10) AS avg_hit_10,
          AVG(hit_rate_10) AS avg_rate_10,
          AVG(hit_count_14) AS avg_hit_14,
          AVG(hit_rate_14) AS avg_rate_14,
          AVG(hit_count_20) AS avg_hit_20,
          AVG(hit_rate_20) AS avg_rate_20,
          AVG(COALESCE(special_hit, 0)) AS special_rate,
          AVG(CASE WHEN hit_count >= 1 THEN 1.0 ELSE 0.0 END) AS hit1_rate,
          AVG(CASE WHEN hit_count >= 2 THEN 1.0 ELSE 0.0 END) AS hit2_rate
        FROM prediction_runs
        WHERE status='REVIEWED'
        GROUP BY strategy
        ORDER BY avg_rate DESC
        """
    ).fetchall()


def get_recent_reviews(conn: sqlite3.Connection, limit: int = 20) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT issue_no, strategy, hit_count, hit_rate, COALESCE(special_hit, 0) AS special_hit, reviewed_at
        FROM prediction_runs
        WHERE status='REVIEWED'
        ORDER BY reviewed_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_draw_issues_desc(conn: sqlite3.Connection, limit: int = 300) -> List[str]:
    rows = conn.execute(
        "SELECT issue_no FROM draws ORDER BY draw_date DESC, issue_no DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [str(r["issue_no"]) for r in rows]


def get_reviewed_runs_for_issue(conn: sqlite3.Connection, issue_no: str) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          id, issue_no, strategy,
          hit_count, hit_rate,
          hit_count_10, hit_rate_10,
          hit_count_14, hit_rate_14,
          hit_count_20, hit_rate_20,
          COALESCE(special_hit, 0) AS special_hit
        FROM prediction_runs
        WHERE issue_no = ? AND status = 'REVIEWED'
        ORDER BY strategy ASC
        """,
        (issue_no,),
    ).fetchall()


def get_picks_for_run(conn: sqlite3.Connection, run_id: int) -> Tuple[List[int], Optional[int]]:
    picks = conn.execute(
        "SELECT pick_type, number FROM prediction_picks WHERE run_id = ? ORDER BY rank ASC",
        (run_id,),
    ).fetchall()
    mains = [p["number"] for p in picks if p["pick_type"] in (None, "MAIN")]
    specials = [p["number"] for p in picks if p["pick_type"] == "SPECIAL"]
    return mains, (specials[0] if specials else None)


def backfill_missing_special_picks(conn: sqlite3.Connection) -> int:
    draws = load_recent_draws(conn, 200)
    if len(draws) < 20:
        return 0
    mined_cfg = ensure_mined_pattern_config(conn, force=False)

    runs = conn.execute(
        """
        SELECT id, strategy
        FROM prediction_runs
        WHERE status='PENDING'
        """
    ).fetchall()
    patched = 0
    for run in runs:
        run_id = int(run["id"])
        existing_special = conn.execute(
            "SELECT 1 FROM prediction_picks WHERE run_id = ? AND pick_type = 'SPECIAL' LIMIT 1",
            (run_id,),
        ).fetchone()
        if existing_special:
            continue

        mains = conn.execute(
            "SELECT number FROM prediction_picks WHERE run_id = ? AND (pick_type = 'MAIN' OR pick_type IS NULL)",
            (run_id,),
        ).fetchall()
        main_set = {int(r["number"]) for r in mains}
        strategy_name = str(run["strategy"])
        cfg = mined_cfg if strategy_name == "pattern_mined_v1" else None
        _, special_number, special_score, _ = generate_strategy(draws, strategy_name, mined_config=cfg)

        if special_number in main_set:
            for n in ALL_NUMBERS:
                if n not in main_set:
                    special_number = n
                    break

        conn.execute(
            """
            INSERT OR IGNORE INTO prediction_picks(run_id, pick_type, number, rank, score, reason)
            VALUES (?, 'SPECIAL', ?, 1, ?, '特别号补齐')
            """,
            (run_id, special_number, float(special_score)),
        )
        patched += 1

    if patched > 0:
        conn.commit()
    return patched


def print_recommendation_sheet(conn: sqlite3.Connection, limit: int = 8) -> None:
    backfill_missing_special_picks(conn)
    rows = get_pending_runs(conn, limit=limit)
    print("\n6/10/14/20 推荐单:")
    if not rows:
        print("  (空)")
        return

    for r in rows:
        mains, special = get_picks_for_run(conn, int(r["id"]))
        pool6 = [int(n) for n in mains]
        pool10 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 10) or pool6)]
        pool14 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 14) or pool6)]
        pool20 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 20) or pool6)]
        strategy_name = STRATEGY_LABELS.get(r["strategy"], r["strategy"])
        special_text = _fmt_num(special) if special is not None else "--"
        p6 = " ".join(_fmt_num(n) for n in pool6)
        p10 = " ".join(_fmt_num(n) for n in pool10)
        p14 = " ".join(_fmt_num(n) for n in pool14)
        p20 = " ".join(_fmt_num(n) for n in pool20)
        print(f"  [{r['issue_no']}] {strategy_name}")
        print(f"    6号池 : {p6} | 特别号: {special_text}")
        print(f"    10号池: {p10} | 特别号: {special_text}")
        print(f"    14号池: {p14} | 特别号: {special_text}")
        print(f"    20号池: {p20} | 特别号: {special_text}")


def print_dashboard(conn: sqlite3.Connection) -> None:
    latest = get_latest_draw(conn)
    if latest:
        nums = " ".join(_fmt_num(n) for n in json.loads(latest["numbers_json"]))
        print(f"最新开奖: {latest['issue_no']} {latest['draw_date']} | 主号: {nums} | 特别号: {_fmt_num(int(latest['special_number']))}")
    else:
        print("暂无开奖数据。")

    print_recommendation_sheet(conn, limit=8)

    print("\n策略平均命中率:")
    stats = get_review_stats(conn)
    if not stats:
        print("  (暂无复盘)")
    for s in stats:
        strategy_name = STRATEGY_LABELS.get(s["strategy"], s["strategy"])
        print(
            f"  - {strategy_name}: 次数={s['c']} 平均命中={s['avg_hit']:.2f} "
            f"命中率6={s['avg_rate'] * 100:.2f}% 10={float(s['avg_rate_10'] or 0) * 100:.2f}% "
            f"14={float(s['avg_rate_14'] or 0) * 100:.2f}% 20={float(s['avg_rate_20'] or 0) * 100:.2f}% "
            f"特别号命中率={s['special_rate'] * 100:.2f}% 至少中1个={s['hit1_rate'] * 100:.2f}% 至少中2个={s['hit2_rate'] * 100:.2f}%"
        )


def cmd_bootstrap(args: argparse.Namespace) -> None:
    conn = connect_db(args.db)
    try:
        init_db(conn)
        configured_urls = parse_url_list(args.third_party_url or [])
        third_party_urls = configured_urls if configured_urls else THIRD_PARTY_URLS_DEFAULT
        if args.source == "official":
            records = fetch_official_records(args.official_url)
            total, inserted, updated = sync_from_records(conn, records, source="official_api")
        elif args.source == "third_party":
            if not third_party_urls:
                raise RuntimeError("Missing --third-party-url")
            records = fetch_records_from_url(
                third_party_urls[0],
                "third-party source",
                third_party_max_pages=args.third_party_max_pages,
            )
            total, inserted, updated = sync_from_records(conn, records, source="third_party_api_1")
        elif args.source == "auto":
            try:
                records, source_label, used_url = fetch_online_records_with_multi_fallback(
                    args.official_url,
                    third_party_urls,
                    third_party_max_pages=args.third_party_max_pages,
                )
                total, inserted, updated = sync_from_records(conn, records, source=source_label)
                print(f"Bootstrap source: {used_url}")
            except Exception:
                total, inserted, updated = sync_from_csv(conn, args.csv, source="bootstrap_csv")
        else:
            total, inserted, updated = sync_from_csv(conn, args.csv, source="bootstrap_csv")
        issue = generate_predictions(conn)
        print(f"Bootstrap done. total={total}, inserted={inserted}, updated={updated}, next_prediction={issue}")
    finally:
        conn.close()


def cmd_sync(args: argparse.Namespace) -> None:
    conn = connect_db(args.db)
    try:
        init_db(conn)
        configured_urls = parse_url_list(args.third_party_url or [])
        third_party_urls = configured_urls if configured_urls else THIRD_PARTY_URLS_DEFAULT
        used_source_url = ""
        if args.source == "official":
            records = fetch_records_from_url(
                args.official_url,
                "official source",
                third_party_max_pages=args.third_party_max_pages,
            )
            if args.require_continuity:
                missing = missing_issues_since_latest(conn, records)
                if missing:
                    raise RuntimeError(
                        f"Continuity check failed. Missing {len(missing)} issues, sample={','.join(missing[:10])}"
                    )
            total, inserted, updated = sync_from_records(conn, records, source="official_api")
            used_source_url = args.official_url
        elif args.source == "third_party":
            if not third_party_urls:
                raise RuntimeError("Missing --third-party-url")
            records = fetch_records_from_url(
                third_party_urls[0],
                "third-party source",
                third_party_max_pages=args.third_party_max_pages,
            )
            if args.require_continuity:
                missing = missing_issues_since_latest(conn, records)
                if missing:
                    raise RuntimeError(
                        f"Continuity check failed. Missing {len(missing)} issues, sample={','.join(missing[:10])}"
                    )
            total, inserted, updated = sync_from_records(conn, records, source="third_party_api_1")
            used_source_url = third_party_urls[0]
        elif args.source == "auto":
            if has_any_draw(conn):
                records, source_label, used_url = fetch_online_records_with_multi_fallback(
                    args.official_url,
                    third_party_urls,
                    third_party_max_pages=args.third_party_max_pages,
                )
                if args.require_continuity:
                    missing = missing_issues_since_latest(conn, records)
                    if missing:
                        raise RuntimeError(
                            f"Continuity check failed. Missing {len(missing)} issues, sample={','.join(missing[:10])}"
                        )
                total, inserted, updated = sync_from_records(conn, records, source=source_label)
                used_source_url = used_url
            else:
                total, inserted, updated = sync_from_csv(conn, args.csv)
        else:
            total, inserted, updated = sync_from_csv(conn, args.csv)
        mined_cfg = ensure_mined_pattern_config(conn, force=args.remine)
        reviewed = review_latest(conn)
        bt_issues, bt_runs = 0, 0
        if args.with_backtest:
            bt_issues, bt_runs = run_historical_backtest(conn, rebuild=False)
        issue = generate_predictions(conn)
        patched = backfill_missing_special_picks(conn)
        print(f"Sync done. total={total}, inserted={inserted}, updated={updated}, reviewed={reviewed}, next_prediction={issue}")
        print(f"Mined config: {json.dumps(mined_cfg, ensure_ascii=False)}")
        if bt_issues > 0:
            print(f"Backtest updated. issues={bt_issues}, strategy_runs={bt_runs}")
        if used_source_url:
            print(f"Sync source: {used_source_url}")
        if patched > 0:
            print(f"Patched missing special picks: {patched}")
    finally:
        conn.close()


def cmd_predict(args: argparse.Namespace) -> None:
    conn = connect_db(args.db)
    try:
        init_db(conn)
        issue = generate_predictions(conn, issue_no=args.issue)
        patched = backfill_missing_special_picks(conn)
        print(f"Predictions generated for {issue}")
        if patched > 0:
            print(f"Patched missing special picks: {patched}")
    finally:
        conn.close()


def cmd_review(args: argparse.Namespace) -> None:
    conn = connect_db(args.db)
    try:
        init_db(conn)
        reviewed = review_issue(conn, args.issue) if args.issue else review_latest(conn)
        print(f"Reviewed runs: {reviewed}")
    finally:
        conn.close()


def cmd_show(args: argparse.Namespace) -> None:
    conn = connect_db(args.db)
    try:
        init_db(conn)
        backfill_missing_special_picks(conn)
        print_dashboard(conn)
    finally:
        conn.close()


def cmd_backtest(args: argparse.Namespace) -> None:
    conn = connect_db(args.db)
    try:
        init_db(conn)
        mined_cfg = ensure_mined_pattern_config(conn, force=args.remine)
        issues, runs = run_historical_backtest(
            conn,
            min_history=args.min_history,
            rebuild=args.rebuild,
            progress_every=args.progress_every,
        )
        print(f"Backtest done. issues={issues}, strategy_runs={runs}, rebuild={args.rebuild}")
        print(f"Mined config: {json.dumps(mined_cfg, ensure_ascii=False)}")
    finally:
        conn.close()


def cmd_mine(args: argparse.Namespace) -> None:
    conn = connect_db(args.db)
    try:
        init_db(conn)
        cfg = ensure_mined_pattern_config(conn, force=True)
        print(f"Mine done. config={json.dumps(cfg, ensure_ascii=False)}")
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local Mark Six predictor (Python + SQLite)")
    p.add_argument("--db", default=DB_PATH_DEFAULT, help=f"SQLite db path (default: {DB_PATH_DEFAULT})")
    p.add_argument("--update", action="store_true", help="Quick sync (same as sync)")
    p.add_argument("--updata", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--update-csv", default=CSV_PATH_DEFAULT, help=f"CSV path used with --update/--updata (default: {CSV_PATH_DEFAULT})")
    p.add_argument(
        "--source",
        choices=["official", "third_party", "csv", "auto"],
        default="auto",
        help="Data source mode: auto=CSV only for first init, then online (official->third_party)",
    )
    p.add_argument("--remine", action="store_true", help="Re-mine pattern config before sync/backtest")
    p.add_argument("--official-url", default=OFFICIAL_URL_DEFAULT, help="Official result JSON URL")
    p.add_argument(
        "--third-party-url",
        action="append",
        default=[],
        help="Third-party API URL (JSON/CSV). Can be repeated or comma-separated. If omitted, built-in defaults are used.",
    )
    p.add_argument(
        "--third-party-max-pages",
        type=int,
        default=THIRD_PARTY_MAX_PAGES_DEFAULT,
        help="Max pages for HTML-style third-party sources (e.g. Lottolyzer).",
    )
    p.add_argument("--require-continuity", action="store_true", default=True, help="Fail update when issue sequence has gaps")
    p.add_argument("--no-require-continuity", dest="require_continuity", action="store_false", help="Allow gaps")
    sub = p.add_subparsers(dest="command", required=False)

    p_boot = sub.add_parser("bootstrap", help="Initial import from CSV and generate next issue predictions")
    p_boot.add_argument("--csv", default=CSV_PATH_DEFAULT, help=f"CSV path (default: {CSV_PATH_DEFAULT})")
    p_boot.add_argument(
        "--source",
        choices=["official", "third_party", "csv", "auto"],
        default="csv",
        help="Data source mode",
    )
    p_boot.add_argument("--official-url", default=OFFICIAL_URL_DEFAULT, help="Official result JSON URL")
    p_boot.add_argument(
        "--third-party-url",
        action="append",
        default=[],
        help="Third-party API URL (JSON/CSV). Can be repeated or comma-separated. If omitted, built-in defaults are used.",
    )
    p_boot.add_argument(
        "--third-party-max-pages",
        type=int,
        default=THIRD_PARTY_MAX_PAGES_DEFAULT,
        help="Max pages for HTML-style third-party sources (e.g. Lottolyzer).",
    )
    p_boot.set_defaults(func=cmd_bootstrap)

    p_sync = sub.add_parser("sync", help="Sync draws from CSV, review latest, generate next prediction")
    p_sync.add_argument("--csv", default=CSV_PATH_DEFAULT, help=f"CSV path (default: {CSV_PATH_DEFAULT})")
    p_sync.add_argument(
        "--source",
        choices=["official", "third_party", "csv", "auto"],
        default="auto",
        help="Data source mode",
    )
    p_sync.add_argument("--official-url", default=OFFICIAL_URL_DEFAULT, help="Official result JSON URL")
    p_sync.add_argument(
        "--third-party-url",
        action="append",
        default=[],
        help="Third-party API URL (JSON/CSV). Can be repeated or comma-separated. If omitted, built-in defaults are used.",
    )
    p_sync.add_argument(
        "--third-party-max-pages",
        type=int,
        default=THIRD_PARTY_MAX_PAGES_DEFAULT,
        help="Max pages for HTML-style third-party sources (e.g. Lottolyzer).",
    )
    p_sync.add_argument("--require-continuity", action="store_true", default=True, help="Fail update when issue sequence has gaps")
    p_sync.add_argument("--no-require-continuity", dest="require_continuity", action="store_false", help="Allow gaps")
    p_sync.add_argument("--with-backtest", action="store_true", help="Run incremental backtest after sync")
    p_sync.set_defaults(func=cmd_sync)

    p_predict = sub.add_parser("predict", help="Generate predictions for next or specified issue")
    p_predict.add_argument("--issue", help="Target issue, e.g. 26/023")
    p_predict.set_defaults(func=cmd_predict)

    p_review = sub.add_parser("review", help="Review pending runs for latest or specified issue")
    p_review.add_argument("--issue", help="Issue to review, e.g. 26/022")
    p_review.set_defaults(func=cmd_review)

    p_show = sub.add_parser("show", help="Show local dashboard summary")
    p_show.set_defaults(func=cmd_show)

    p_backtest = sub.add_parser("backtest", help="Run historical backtest for all draw issues")
    p_backtest.add_argument("--min-history", type=int, default=20, help="Min history window before first backtest issue")
    p_backtest.add_argument("--rebuild", action="store_true", help="Rebuild reviewed backtest runs from scratch")
    p_backtest.add_argument("--remine", action="store_true", help="Re-mine pattern config before backtest")
    p_backtest.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Print backtest progress every N processed issues (0 to disable)",
    )
    p_backtest.set_defaults(func=cmd_backtest)

    p_mine = sub.add_parser("mine", help="Mine best pattern parameters from history")
    p_mine.set_defaults(func=cmd_mine)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.update or args.updata:
        args.csv = args.update_csv
        cmd_sync(args)
        return
    if not args.command:
        parser.error("Please provide a subcommand, or use --update.")
    args.func(args)


if __name__ == "__main__":
    main()
