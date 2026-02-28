# 香港六合彩预测项目（V1 骨架）

## 功能范围（当前版本）
- 一次性历史初始化：从 `Mark_Six.csv` 导入历史开奖
- 自动增量更新：通过 Vercel Cron 调用 `/api/jobs/sync-latest` 同步最新期
- 多策略预测：`balanced_v1`（默认）、`hot_v1`、`cold_rebound_v1`、`momentum_v1`
- 开奖复盘：自动计算每个策略命中号码、命中数和命中率
- 历史补录：支持按年份区间导入更早 CSV（例如 1993-2007）
- 数据审计：检查号码合法性、期号连续性、时间顺序

## 本地启动
1. 安装依赖
```bash
npm install
```

2. 配置环境变量
```bash
cp .env.example .env
```

3. 初始化数据库
```bash
npx prisma generate
npx prisma migrate dev --name init
```

4. 一次性导入历史数据（只需首次）
```bash
npm run bootstrap:history
```

5. 启动项目
```bash
npm run dev
```

## 生产环境建议（Vercel）
- 使用外部 Postgres（Neon / Supabase / RDS），不要把 CSV 当线上数据库。
- Vercel 只负责运行 Web/API/Cron，持久化数据放在 Postgres。
- Vercel 环境变量至少配置：
  - `DATABASE_URL`
  - `CRON_SECRET`
  - `RESULT_PROVIDER=official`（推荐）
  - `OFFICIAL_RESULT_URL`（官方结果 JSON 地址）

## 关键 API
- `GET /api/jobs/sync-latest`
  - 功能：同步最新开奖 + 对已开奖期做复盘 + 生成下一期预测
  - 认证：支持 `Authorization: Bearer <CRON_SECRET>`（Vercel Cron）或 `x-cron-secret: <CRON_SECRET>`
- `POST /api/predictions/generate`
  - 功能：手动生成预测
  - 请求体示例：
```json
{
  "issueNo": "26/001",
  "strategies": ["balanced_v1", "hot_v1"]
}
```

## 数据源模式
- `RESULT_PROVIDER=official`：优先读取官方结果源（推荐）
- `RESULT_PROVIDER=csv`：读取 `RESULT_CSV_URL` 或本地 `LOCAL_RESULT_CSV_PATH`
- 未设置 `RESULT_PROVIDER`：先尝试官方，再回退到 CSV

官方模式建议变量：
```env
RESULT_PROVIDER=official
OFFICIAL_RESULT_URL=https://bet.hkjc.com/contentserver/jcbw/cmc/last30draw.json
OFFICIAL_SOURCE_REQUIRED=true
```

说明：
- 官方地址可能调整，若解析失败可先把 `OFFICIAL_SOURCE_REQUIRED=false`，系统会自动回退 CSV。
- 一旦你确认官方接口稳定，建议将 `OFFICIAL_SOURCE_REQUIRED=true`，避免 silently fallback。

## 补充 2008 年前历史数据
1. 准备 CSV 文件，放到 `data/history/`，例如：
   - `data/history/1997.csv`
   - `data/history/1998.csv`
   - `data/history/2007.csv`
2. CSV 至少包含列：
   - `期号`
   - `日期`
   - `中奖号码`
   - `特别号码`
3. 执行补录（示例导入 1993-2007）：
```bash
npm run backfill:history -- --path ./data/history --from-year 1993 --to-year 2007
```
4. 跑质量检查：
```bash
npm run audit:history
```
5. 若审计通过，可重新生成下一期预测：
```bash
npm run predict:next
```

## 用 `Mark_Six.csv` 初始化当前库
默认会读取根目录 `Mark_Six.csv`（可由 `LOCAL_RESULT_CSV_PATH` 覆盖）：
```bash
npm run bootstrap:history
```
如果之前已经初始化过，想用新 CSV 重新全量校正：
```bash
npm run bootstrap:history -- --force
```

## 部署到 Vercel Postgres 并自动增量
1. 推送代码到 GitHub。
2. 在 Vercel 导入仓库。
3. 在 Vercel 项目中创建 Postgres（Storage -> Postgres），复制连接串到 `DATABASE_URL`。
4. 在 Vercel 项目环境变量中设置：
   - `DATABASE_URL`
   - `CRON_SECRET`（自行生成高强度随机字符串）
   - `RESULT_PROVIDER=official`
   - `OFFICIAL_RESULT_URL`
   - `OFFICIAL_SOURCE_REQUIRED=true`
5. 在 Vercel 项目 `Build Command` 设置：
```bash
npm run vercel-build
```
6. 首次部署完成后，手动触发一次：
   - 访问 `/api/jobs/sync-latest`（带 Bearer token）或在 Vercel Functions 页面触发该路由。
7. 之后由 `vercel.json` 的 cron 自动触发增量同步。

说明：
- 自动增量的关键是：`OFFICIAL_RESULT_URL` 能持续返回最新开奖结果。
- 如官方格式有变更，需同步更新解析逻辑（`src/lib/official-source.ts`）。

## GitHub 上传与 Vercel 部署

### 1) 推送到 GitHub
```bash
git init
git add .
git commit -m "feat: init marksix predictor v1 skeleton"
# 替换为你的仓库地址
git remote add origin git@github.com:<your-name>/<repo>.git
git branch -M main
git push -u origin main
```

### 2) 连接 Vercel
1. 在 Vercel 导入该 GitHub 仓库
2. 配置环境变量：
   - `DATABASE_URL`
   - `CRON_SECRET`
   - `RESULT_PROVIDER`（推荐 `official`）
   - `OFFICIAL_RESULT_URL`
   - `OFFICIAL_SOURCE_REQUIRED`
   - `RESULT_CSV_URL`（可选，回退源）
   - `LOCAL_RESULT_CSV_PATH`（可选，本地调试）
   - `HISTORY_CSV_DIR`（可选，本地补历史默认目录）
3. 部署后，Vercel 会按 `vercel.json` 的 cron 触发增量同步

## 关于“要不要在 Codex 里设置 GitHub”
- 不需要在 Codex 做特殊配置。
- 你只需要本机已配置好 Git 凭据（SSH key 或 GitHub Token），然后在终端里按上面的 `git remote add` / `git push` 执行即可。
- 如果你希望我继续，我可以下一步直接帮你整理 `.env`、执行本地初始化命令，并检查项目是否可运行。
