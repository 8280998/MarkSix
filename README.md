# 本地 Python 版（零第三方依赖）

脚本：`marksix_local.py`

## 环境
- Python 3.10+
- 不需要 `pip install`

## 快速开始
在项目根目录执行：

```bash
# 1) 首次导入 Mark_Six.csv 并生成下一期预测
python3 marksix_local.py bootstrap --csv Mark_Six.csv

# 2) 查看当前摘要（最新开奖、待复盘预测、策略统计）
python3 marksix_local.py show

# 3) 当你更新 CSV 后，增量同步 + 复盘 + 生成新预测
python3 marksix_local.py sync --csv Mark_Six.csv

# 4) 快捷更新官方数据
python3 marksix_local.py --update

# 5) 指定第三方数据源（官方失败时可切换）
python3 marksix_local.py --update --source third_party --third-party-url "https://example.com/marksix.json"

# 6) 多第三方回退（可重复传参）
python3 marksix_local.py --update --source auto \\
  --third-party-url "https://source-a.example/marksix.json" \\
  --third-party-url "https://source-b.example/marksix.csv"

# 7) Lottolyzer 分页抓取页数（默认 60 页）
python3 marksix_local.py --update --source auto --third-party-max-pages 60
```

说明：预测结果为 `6+1`（6 个主号 + 1 个特别号），复盘会单独统计特别号命中率。
`show` 命令会输出“6+1推荐单”格式，便于直接复制。

## 命令说明
```bash
python3 marksix_local.py bootstrap --csv <文件>
python3 marksix_local.py sync --source official
python3 marksix_local.py sync --source third_party --third-party-url "<第三方URL>"
python3 marksix_local.py sync --source csv --csv <文件>
python3 marksix_local.py sync --source auto --with-backtest
python3 marksix_local.py --updata --source auto --third-party-url "<第三方URL1>" --third-party-url "<第三方URL2>"
python3 marksix_local.py backtest --rebuild
python3 marksix_local.py backtest --rebuild --remine --progress-every 50
python3 marksix_local.py mine
python3 marksix_local.py predict [--issue 26/023]
python3 marksix_local.py review [--issue 26/022]
python3 marksix_local.py show
```

官方源默认地址：
`https://bet.hkjc.com/contentserver/jcbw/cmc/last30draw.json`

数据源规则（默认 `--source auto`）：
- 数据库为空时：用 `Mark_Six.csv` 做一次初始化
- 数据库已有历史后：后续更新只走在线源（先官方，失败后自动尝试第三方）
- 默认开启连续性检查：发现期号断档会直接失败并提示缺失期号样例（避免静默漏数据）
- 如你确认数据源不完整但仍想继续更新，可加 `--no-require-continuity`

规律挖掘引擎：
- 新增策略：`规律挖掘 (pattern_mined_v1)`，自动从历史数据搜索窗口与权重参数
- 新增策略：`集成投票 (ensemble_v2)`，融合热号/冷号/动量/组合/规律挖掘的排名投票
- 可手动重挖掘：`python3 marksix_local.py mine`
- 回测建议重建：`python3 marksix_local.py backtest --rebuild --remine`
- 长回测建议加进度输出：`python3 marksix_local.py backtest --rebuild --remine --progress-every 50`
- V3 覆盖池：每个策略同时输出 `6/10/14/20` 候选池并统计对应命中率

第三方源格式支持：
- JSON（常见字段：`issueNo/drawNo`、`date/drawDate`、`n1..n6`、`specialNumber`）
- CSV（字段与 `Mark_Six.csv` 同类格式）

内置第三方源（未传 `--third-party-url` 时自动使用）：
- `https://lottolyzer.com/history/hong-kong/mark-six/page/1/per-page/50/summary-view`

## 本地 Web 页面
```bash
python3 web_app.py --host 127.0.0.1 --port 8080
```
打开浏览器访问：
- `http://127.0.0.1:8080/`（预测看板）
- `http://127.0.0.1:8080/review`（复盘总览）
- `http://127.0.0.1:8080/review?issue=26/022`（按期查看预测与准确率）

首页每个策略卡片会同时显示 `6/10/14/20` 四档小型命中率对比条，无需切换参数。

## 数据库
- 默认数据库文件：`local_python/marksix_local.db`（按脚本所在目录固定）
- 默认 CSV：`local_python/Mark_Six.csv`（按脚本所在目录固定）
- 可通过 `--db`、`--csv` 自定义路径

例如：
```bash
python3 marksix_local.py --db ./data/local.db show
```
