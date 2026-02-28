#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from marksix_local import (
    DB_PATH_DEFAULT,
    STRATEGY_LABELS,
    connect_db,
    generate_predictions,
    get_draw_issues_desc,
    get_latest_draw,
    get_pending_runs,
    get_picks_for_run,
    get_pool_numbers_for_run,
    get_recent_reviews,
    get_reviewed_runs_for_issue,
    get_review_stats,
    init_db,
)


def _fmt_num(n: int) -> str:
    return str(n).zfill(2)


def _pool_line(
    label: str,
    nums: list[int],
    winning_main: set[int] | None = None,
    hit_count: int | None = None,
    hit_rate: float | None = None,
    special: int | None = None,
    special_text: str | None = None,
    matched_text: str | None = None,
) -> str:
    chips = []
    for n in nums:
        cls = "pool-num pool-hit" if winning_main and int(n) in winning_main else "pool-num"
        chips.append(f"<span class='{cls}'>{_fmt_num(int(n))}</span>")
    tail = ""
    if special is not None:
        tail += f" <span class='pool-meta'>｜ 特别号 {_fmt_num(int(special))}</span>"
    if hit_count is not None:
        tail += f" <span class='pool-meta'>｜ 命中数：{hit_count}/6"
        if matched_text:
            tail += f" {html.escape(matched_text)}"
        tail += "</span>"
    if hit_rate is not None:
        tail += f" <span class='pool-meta'>｜ 命中率：{hit_rate*100:.2f}%</span>"
    if special_text:
        tail += f" <span class='pool-meta'>｜ 特别号码：{html.escape(special_text)}</span>"
    return f"<div class='pool-row'><span class='pool-label'>{html.escape(label)}：</span>{''.join(chips)}{tail}</div>"


def _layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang=\"zh-HK\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg:#f5f1e8; --card:#fffaf1; --line:#ded4c2; --text:#171717; --muted:#666; --accent:#0f6a54;
      --hit:#f59e0b; --hit-special:#dc2626;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif; background:var(--bg); color:var(--text); }}
    .wrap {{ max-width:1100px; margin:20px auto; padding:0 14px; }}
    .top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
    .tabs a {{ margin-left:12px; color:var(--accent); text-decoration:none; font-weight:600; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:12px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:10px; }}
    .grid5 {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; }}
    .stack {{ display:flex; flex-direction:column; gap:10px; }}
    .ball {{ display:inline-flex; width:32px; height:32px; border-radius:50%; background:var(--accent); color:#fff; align-items:center; justify-content:center; margin-right:7px; margin-bottom:7px; font-weight:700; }}
    .special {{ background:#b91c1c; }}
    .hit {{ background:var(--hit); color:#111; box-shadow:0 0 0 2px #7a4a00 inset; }}
    .hit-special {{ background:var(--hit-special); color:#fff; box-shadow:0 0 0 2px #7f1d1d inset; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    .pool-row {{ margin-top:6px; font-size:14px; color:#3f3f3f; line-height:1.6; }}
    .pool-label {{ color:#444; font-weight:600; }}
    .pool-num {{ display:inline-block; min-width:26px; padding:0 4px; border-radius:4px; background:#ede7d9; text-align:center; margin-right:4px; font-weight:600; }}
    .pool-hit {{ background:#f7c66b; color:#2a1600; }}
    .pool-meta {{ color:#575757; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); }}
    th, td {{ padding:9px; border-bottom:1px solid var(--line); text-align:left; font-size:14px; }}
    .picker {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
    .picker select, .picker button {{ font-size:20px; padding:4px 10px; border:1px solid #999; border-radius:6px; background:#efefef; }}
    .picker label {{ font-size:44px; font-weight:700; line-height:1; }}
    @media (max-width: 768px) {{
      .picker label {{ font-size:28px; }}
      .picker select, .picker button {{ font-size:18px; }}
      .grid5 {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    }}
    @media (max-width: 520px) {{
      .grid5 {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"top\">
      <h2 style=\"margin:0\">香港六合彩本地看板</h2>
      <div class=\"tabs\"><a href=\"/\">预测</a><a href=\"/review\">复盘</a></div>
    </div>
    {body}
  </div>
</body>
</html>"""


def render_home(db_path: str, issue_no: str = "") -> str:
    conn = connect_db(db_path)
    init_db(conn)
    latest = get_latest_draw(conn)
    if latest:
        # Ensure next issue always has full strategy set (including pattern_mined_v1).
        try:
            generate_predictions(conn)
        except Exception:
            pass
    issues = get_draw_issues_desc(conn, limit=400)
    selected_issue = issue_no if issue_no in issues else (issues[0] if issues else "")

    selected_draw = None
    if selected_issue:
        selected_draw = conn.execute(
            "SELECT issue_no, draw_date, numbers_json, special_number FROM draws WHERE issue_no = ?",
            (selected_issue,),
        ).fetchone()
    selected_runs = (
        conn.execute(
            """
            SELECT
              id, issue_no, strategy, status,
              hit_count, hit_rate,
              hit_count_10, hit_rate_10,
              hit_count_14, hit_rate_14,
              hit_count_20, hit_rate_20,
              COALESCE(special_hit, 0) AS special_hit
            FROM prediction_runs
            WHERE issue_no = ?
            ORDER BY strategy ASC
            """,
            (selected_issue,),
        ).fetchall()
        if selected_issue
        else []
    )
    pending_all = get_pending_runs(conn, limit=40)
    next_issue = str(pending_all[0]["issue_no"]) if pending_all else ""
    next_runs = [r for r in pending_all if str(r["issue_no"]) == next_issue]

    latest_html = "<p class='muted'>暂无开奖数据</p>"
    if latest:
        nums = json.loads(latest["numbers_json"])
        latest_html = (
            f"<div class='card'><div><b>最新开奖:</b> {html.escape(latest['issue_no'])} {html.escape(latest['draw_date'])}</div>"
            f"<div style='margin-top:8px'>"
            + "".join(f"<span class='ball'>{_fmt_num(int(n))}</span>" for n in nums)
            + f"<span class='ball special'>{_fmt_num(int(latest['special_number']))}</span>"
            + "</div><div class='muted'>最后一个红球为特别号</div></div>"
        )

    options_html = "".join(
        f"<option value='{html.escape(i)}' {'selected' if i == selected_issue else ''}>{html.escape(i)}</option>"
        for i in issues
    )
    picker_html = (
        "<div class='card'><form method='get' action='/' class='picker'>"
        "<label>选择开奖期数：</label>"
        f"<select name='issue'>{options_html}</select>"
        "<button type='submit'>查看</button>"
        "</form></div>"
    )

    draw_html = "<div class='card'>暂无该期开奖数据</div>"
    winning_main: set[int] = set()
    winning_special: int | None = None
    selected_date_text = ""
    selected_is_latest = bool(latest and selected_issue and str(latest["issue_no"]) == str(selected_issue))
    if selected_is_latest:
        latest_html = ""
    if selected_draw:
        nums = [int(n) for n in json.loads(selected_draw["numbers_json"])]
        winning_main = set(nums)
        winning_special = int(selected_draw["special_number"])
        selected_date_text = str(selected_draw["draw_date"])
        balls = "".join(f"<span class='ball'>{_fmt_num(n)}</span>" for n in nums)
        draw_html = (
            f"<div class='card'><b>开奖期号:</b> {html.escape(selected_draw['issue_no'])} "
            f"<span class='muted'>{html.escape(selected_draw['draw_date'])}</span>"
            f"<div style='margin-top:8px'>{balls}<span class='ball special'>{_fmt_num(winning_special)}</span></div></div>"
        )

    cards = []
    for r in selected_runs:
        mains, special = get_picks_for_run(conn, int(r["id"]))
        pool6 = [int(n) for n in mains]
        pool10 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 10) or pool6)]
        pool14 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 14) or pool6)]
        pool20 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 20) or pool6)]
        strategy_name = STRATEGY_LABELS.get(r["strategy"], r["strategy"])
        matched = sorted([int(n) for n in pool6 if int(n) in winning_main])
        matched_text = "｜".join(_fmt_num(n) for n in matched) if matched else "--"
        special_hit = special is not None and winning_special is not None and int(special) == winning_special
        if str(r["status"]) == "REVIEWED":
            hit_count = int(r["hit_count"] or 0)
            hit_rate: float | None = float(r["hit_rate"] or 0)
            hit_rate_10: float | None = None if r["hit_rate_10"] is None else float(r["hit_rate_10"])
            hit_rate_14: float | None = None if r["hit_rate_14"] is None else float(r["hit_rate_14"])
            hit_rate_20: float | None = None if r["hit_rate_20"] is None else float(r["hit_rate_20"])

            # Fallback: for old reviewed records without pool-rate columns, recompute from saved pools.
            if winning_main:
                if hit_rate_10 is None:
                    hit_rate_10 = len([n for n in pool10 if int(n) in winning_main]) / 6.0 if pool10 else None
                if hit_rate_14 is None:
                    hit_rate_14 = len([n for n in pool14 if int(n) in winning_main]) / 6.0 if pool14 else None
                if hit_rate_20 is None:
                    hit_rate_20 = len([n for n in pool20 if int(n) in winning_main]) / 6.0 if pool20 else None
            hit_count_10 = len([n for n in pool10 if int(n) in winning_main]) if winning_main else None
            hit_count_14 = len([n for n in pool14 if int(n) in winning_main]) if winning_main else None
            hit_count_20 = len([n for n in pool20 if int(n) in winning_main]) if winning_main else None
            pool_rows = (
                _pool_line(
                    "6号池",
                    pool6,
                    winning_main=winning_main if winning_main else None,
                    hit_count=hit_count,
                    hit_rate=hit_rate,
                    special=special,
                    special_text=("命中" if int(r["special_hit"] or 0) == 1 else "未中"),
                    matched_text=matched_text,
                )
                + _pool_line(
                    "10号池",
                    pool10,
                    winning_main=winning_main if winning_main else None,
                    hit_count=hit_count_10,
                    hit_rate=hit_rate_10,
                    special=special,
                    special_text=("命中" if int(r["special_hit"] or 0) == 1 else "未中"),
                )
                + _pool_line(
                    "14号池",
                    pool14,
                    winning_main=winning_main if winning_main else None,
                    hit_count=hit_count_14,
                    hit_rate=hit_rate_14,
                    special=special,
                    special_text=("命中" if int(r["special_hit"] or 0) == 1 else "未中"),
                )
                + _pool_line(
                    "20号池",
                    pool20,
                    winning_main=winning_main if winning_main else None,
                    hit_count=hit_count_20,
                    hit_rate=hit_rate_20,
                    special=special,
                    special_text=("命中" if int(r["special_hit"] or 0) == 1 else "未中"),
                )
            )
        else:
            pool_rows = (
                _pool_line("6号池", pool6, special=special, special_text="待开奖")
                + _pool_line("10号池", pool10, special=special, special_text="待开奖")
                + _pool_line("14号池", pool14, special=special, special_text="待开奖")
                + _pool_line("20号池", pool20, special=special, special_text="待开奖")
            )
        cards.append(
            f"<div class='card'><div><b>{html.escape(strategy_name)}</b></div>"
            f"<div class='muted'>期号: {html.escape(r['issue_no'])}</div>"
            f"{pool_rows}</div>"
        )

    if not cards:
        cards.append("<div class='card'>该期暂无预测记录，请先执行 sync/backtest。</div>")

    next_cards = []
    for r in next_runs:
        mains, special = get_picks_for_run(conn, int(r["id"]))
        pool6 = [int(n) for n in mains]
        pool10 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 10) or pool6)]
        pool14 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 14) or pool6)]
        pool20 = [int(n) for n in (get_pool_numbers_for_run(conn, int(r["id"]), 20) or pool6)]
        strategy_name = STRATEGY_LABELS.get(r["strategy"], r["strategy"])
        pool_rows = (
            _pool_line("6号池", pool6, special=special, special_text="待开奖")
            + _pool_line("10号池", pool10, special=special, special_text="待开奖")
            + _pool_line("14号池", pool14, special=special, special_text="待开奖")
            + _pool_line("20号池", pool20, special=special, special_text="待开奖")
        )
        next_cards.append(
            "<div class='card'>"
            f"<div><b>{html.escape(strategy_name)}</b></div>"
            f"<div class='muted'>期号: {html.escape(r['issue_no'])}（下期预测）</div>"
            f"{pool_rows}"
            "</div>"
        )

    conn.close()
    next_section = ""
    if next_cards:
        next_section = (
            f"<div class='card'><b>下期预测：{html.escape(next_issue)}</b></div>"
            + "<div class='stack'>"
            + "".join(next_cards)
            + "</div>"
        )
    body = (
        picker_html
        + latest_html
        + draw_html
        + f"<div class='card'><b>{html.escape(selected_date_text) if selected_date_text else '本期'} 回测结果</b></div>"
        + "<div class='stack'>"
        + "".join(cards)
        + "</div>"
        + next_section
    )
    return _layout("预测看板", body)


def render_review(db_path: str) -> str:
    conn = connect_db(db_path)
    init_db(conn)
    stats = get_review_stats(conn)
    recents = get_recent_reviews(conn, limit=30)

    stat_rows = "".join(
        (
            "<tr>"
            f"<td>{html.escape(STRATEGY_LABELS.get(s['strategy'], s['strategy']))}</td>"
            f"<td>{int(s['c'])}</td>"
            f"<td>{float(s['avg_hit'] or 0):.2f}</td>"
            f"<td>{float(s['avg_rate'] or 0) * 100:.2f}%</td>"
            f"<td>{float(s['avg_rate_10'] or 0) * 100:.2f}%</td>"
            f"<td>{float(s['avg_rate_14'] or 0) * 100:.2f}%</td>"
            f"<td>{float(s['avg_rate_20'] or 0) * 100:.2f}%</td>"
            f"<td>{float(s['special_rate'] or 0) * 100:.2f}%</td>"
            f"<td>{float(s['hit1_rate'] or 0) * 100:.2f}%</td>"
            f"<td>{float(s['hit2_rate'] or 0) * 100:.2f}%</td>"
            "</tr>"
        )
        for s in stats
    )

    recent_rows = "".join(
        (
            "<tr>"
            f"<td>{html.escape(r['issue_no'])}</td>"
            f"<td>{html.escape(STRATEGY_LABELS.get(r['strategy'], r['strategy']))}</td>"
            f"<td>{int(r['hit_count'] or 0)}</td>"
            f"<td>{float(r['hit_rate'] or 0) * 100:.2f}%</td>"
            f"<td>{'命中' if int(r['special_hit'] or 0) == 1 else '未中'}</td>"
            "</tr>"
        )
        for r in recents
    )

    if not stat_rows:
        stat_rows = "<tr><td colspan='10'>暂无复盘数据</td></tr>"
    if not recent_rows:
        recent_rows = "<tr><td colspan='5'>暂无复盘记录</td></tr>"

    conn.close()
    body = (
        "<div class='card'><b>策略总览</b><table style='margin-top:8px'><thead><tr>"
        "<th>策略</th><th>次数</th><th>平均命中</th><th>命中率6</th><th>命中率10</th><th>命中率14</th><th>命中率20</th><th>特别号</th><th>≥1命中</th><th>≥2命中</th>"
        "</tr></thead><tbody>"
        + stat_rows
        + "</tbody></table></div>"
        "<div class='card'><b>最近复盘</b><table style='margin-top:8px'><thead><tr>"
        "<th>期号</th><th>策略</th><th>命中数</th><th>命中率</th><th>特别号</th>"
        "</tr></thead><tbody>"
        + recent_rows
        + "</tbody></table></div>"
    )
    return _layout("复盘看板", body)


def render_issue_review(db_path: str, issue_no: str) -> str:
    conn = connect_db(db_path)
    init_db(conn)

    issues = get_draw_issues_desc(conn, limit=400)
    selected_issue = issue_no if issue_no in issues else (issues[0] if issues else "")
    reviewed_runs = get_reviewed_runs_for_issue(conn, selected_issue) if selected_issue else []
    draw = None
    if selected_issue:
        draw = conn.execute(
            "SELECT issue_no, draw_date, numbers_json, special_number FROM draws WHERE issue_no = ?",
            (selected_issue,),
        ).fetchone()

    options_html = "".join(
        f"<option value='{html.escape(i)}' {'selected' if i == selected_issue else ''}>{html.escape(i)}</option>"
        for i in issues
    )
    form_html = (
        "<div class='card'><form method='get' action='/review'>"
        "<label><b>选择开奖期数：</b></label> "
        f"<select name='issue'>{options_html}</select> "
        "<button type='submit'>查看</button>"
        "</form></div>"
    )

    draw_html = "<div class='card'>暂无该期开奖数据</div>"
    if draw:
        nums = json.loads(draw["numbers_json"])
        balls = "".join(f"<span class='ball'>{_fmt_num(int(n))}</span>" for n in nums)
        draw_html = (
            f"<div class='card'><b>开奖期号:</b> {html.escape(draw['issue_no'])} "
            f"<span class='muted'>{html.escape(draw['draw_date'])}</span>"
            f"<div style='margin-top:8px'>{balls}<span class='ball special'>{_fmt_num(int(draw['special_number']))}</span></div></div>"
        )

    cards: list[str] = []
    for run in reviewed_runs:
        mains, special = get_picks_for_run(conn, int(run["id"]))
        balls = "".join(f"<span class='ball'>{_fmt_num(int(n))}</span>" for n in mains)
        sball = f"<span class='ball special'>{_fmt_num(int(special))}</span>" if special is not None else ""
        strategy_name = STRATEGY_LABELS.get(run["strategy"], run["strategy"])
        cards.append(
            "<div class='card'>"
            f"<div><b>{html.escape(strategy_name)}</b></div>"
            f"<div style='margin-top:8px'>{balls}{sball}</div>"
            f"<div class='muted'>命中数: {int(run['hit_count'] or 0)} / 6 | 命中率: {float(run['hit_rate'] or 0)*100:.2f}% | "
            f"特别号: {'命中' if int(run['special_hit'] or 0)==1 else '未中'}</div>"
            "</div>"
        )

    if not cards:
        cards.append("<div class='card'>该期暂无回测结果，请先执行同步或 backtest。</div>")

    conn.close()
    body = form_html + draw_html + "<div class='grid'>" + "".join(cards) + "</div>"
    return _layout("按期复盘", body)


class Handler(BaseHTTPRequestHandler):
    db_path = DB_PATH_DEFAULT

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            issue = (query.get("issue") or [""])[0]
            self._send_html(render_home(self.db_path, issue_no=issue))
            return
        if parsed.path == "/review":
            issue = (query.get("issue") or [""])[0]
            if issue:
                self._send_html(render_issue_review(self.db_path, issue))
            else:
                self._send_html(render_review(self.db_path))
            return
        self.send_response(404)
        self.end_headers()

    def _send_html(self, content: str) -> None:
        encoded = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Mark Six dashboard web server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    parser.add_argument("--db", default=DB_PATH_DEFAULT, help="SQLite db path")
    args = parser.parse_args()

    Handler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web running: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
