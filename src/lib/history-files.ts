import fs from "node:fs";
import path from "node:path";
import { parseDrawCsv } from "@/lib/csv";
import { type CsvDrawRecord } from "@/lib/types";

function readCsvFile(filePath: string): CsvDrawRecord[] {
  const raw = fs.readFileSync(filePath, "utf8");
  return parseDrawCsv(raw);
}

export function loadRecordsFromPath(inputPath: string): CsvDrawRecord[] {
  const fullPath = path.resolve(process.cwd(), inputPath);

  if (!fs.existsSync(fullPath)) {
    throw new Error(`Path not found: ${fullPath}`);
  }

  const stat = fs.statSync(fullPath);
  if (stat.isFile()) {
    return readCsvFile(fullPath);
  }

  if (!stat.isDirectory()) {
    throw new Error(`Unsupported path type: ${fullPath}`);
  }

  const files = fs
    .readdirSync(fullPath)
    .filter((name) => name.toLowerCase().endsWith(".csv"))
    .sort((a, b) => a.localeCompare(b));

  const merged = new Map<string, CsvDrawRecord>();
  for (const fileName of files) {
    const filePath = path.join(fullPath, fileName);
    for (const record of readCsvFile(filePath)) {
      merged.set(record.issueNo, record);
    }
  }

  return [...merged.values()].sort((a, b) => a.drawDate.getTime() - b.drawDate.getTime());
}

export function filterByYearRange(records: CsvDrawRecord[], fromYear?: number, toYear?: number) {
  return records.filter((r) => {
    const year = r.drawDate.getUTCFullYear();
    if (fromYear && year < fromYear) {
      return false;
    }
    if (toYear && year > toYear) {
      return false;
    }
    return true;
  });
}
