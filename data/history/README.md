# 历史数据补录目录

把更早年份的 CSV 放在这个目录，例如：

- `1997.csv`
- `1998.csv`
- `1999.csv`

## CSV 列格式要求
必须和当前 `six.csv` 兼容，至少需要这几列：

- `期号`（例如 `08/001`）
- `日期`（例如 `2008-01-05`）
- `中奖号码`（例如 `"3,8,12,27,33,45"`）
- `特别号码`（例如 `19`）

其余列可以存在，也可以为空。

## 导入命令
```bash
npm run backfill:history -- --path ./data/history --from-year 1993 --to-year 2007
```

导入后运行质量检查：
```bash
npm run audit:history
```
