import { parse } from "csv-parse/sync";
import fs from "node:fs";
import path from "node:path";
import { type CsvDrawRecord } from "@/lib/types";

const ISSUE_KEYS = ["期号", "期數"];
const DATE_KEYS = ["日期"];
const COMBINED_NUMBERS_KEYS = ["中奖号码", "中獎號碼"];
const SPECIAL_KEYS = ["特别号码", "特別號碼"];

function normalizeHeaderKey(key: string): string {
  return key.replace(/\uFEFF/g, "").trim();
}

function pickValue(row: Record<string, string>, keys: string[]): string | undefined {
  for (const k of keys) {
    if (row[k] !== undefined && row[k] !== null && `${row[k]}`.trim() !== "") {
      return `${row[k]}`.trim();
    }
  }
  return undefined;
}

function parseNumbers(value: string): number[] {
  return value
    .split(",")
    .map((n) => Number(n.trim()))
    .filter((n) => Number.isInteger(n) && n >= 1 && n <= 49);
}

function parseSplitNumberColumns(row: Record<string, string>): number[] {
  const n1Key = ["中奖号码 1", "中獎號碼 1", "1"].find(
    (k) => row[k] !== undefined && `${row[k]}`.trim() !== "",
  );
  if (!n1Key) {
    return [];
  }

  const keys = [n1Key, "2", "3", "4", "5", "6"];
  if (keys.some((k) => row[k] === undefined || `${row[k]}`.trim() === "")) {
    return [];
  }

  return keys
    .map((k) => Number(`${row[k]}`.trim()))
    .filter((n) => Number.isInteger(n) && n >= 1 && n <= 49);
}

export function parseDrawCsv(csvRaw: string): CsvDrawRecord[] {
  const records = parse(csvRaw, {
    columns: true,
    skip_empty_lines: true,
    trim: true,
  }) as Record<string, string>[];

  return records
    .map((rawRow) => {
      const row: Record<string, string> = {};
      for (const [k, v] of Object.entries(rawRow)) {
        row[normalizeHeaderKey(k)] = v;
      }

      const issueNo = pickValue(row, ISSUE_KEYS);
      const drawDateText = pickValue(row, DATE_KEYS);
      const drawDate = drawDateText ? new Date(`${drawDateText}T12:00:00Z`) : null;

      let numbers: number[] = [];
      const combined = pickValue(row, COMBINED_NUMBERS_KEYS);
      if (combined) {
        numbers = parseNumbers(combined);
      } else {
        numbers = parseSplitNumberColumns(row);
      }

      const specialText = pickValue(row, SPECIAL_KEYS);
      const specialNumber = Number(specialText);

      if (!issueNo || !drawDate || Number.isNaN(drawDate.getTime())) {
        return null;
      }
      if (numbers.length !== 6) {
        return null;
      }
      if (!Number.isInteger(specialNumber) || specialNumber < 1 || specialNumber > 49) {
        return null;
      }

      return {
        issueNo,
        drawDate,
        numbers,
        specialNumber,
      } satisfies CsvDrawRecord;
    })
    .filter((v): v is CsvDrawRecord => Boolean(v))
    .sort((a, b) => a.drawDate.getTime() - b.drawDate.getTime());
}

export function readLocalCsv(filePath: string): string {
  const full = path.resolve(process.cwd(), filePath);
  return fs.readFileSync(full, "utf8");
}
