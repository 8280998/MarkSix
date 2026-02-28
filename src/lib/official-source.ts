import { type CsvDrawRecord } from "@/lib/types";

type OfficialRow = Record<string, unknown>;

function parseDate(input: unknown): Date | null {
  if (typeof input !== "string") {
    return null;
  }

  const text = input.trim();
  if (!text) {
    return null;
  }

  // yyyy-mm-dd
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    const d = new Date(`${text}T12:00:00Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  // dd/mm/yyyy
  const m = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (m) {
    const dd = Number(m[1]);
    const mm = Number(m[2]);
    const yyyy = Number(m[3]);
    const d = new Date(Date.UTC(yyyy, mm - 1, dd, 12, 0, 0));
    return Number.isNaN(d.getTime()) ? null : d;
  }

  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? null : d;
}

function toInt(value: unknown): number | null {
  const n = Number(`${value ?? ""}`.trim());
  if (!Number.isInteger(n)) {
    return null;
  }
  return n;
}

function parseNumberList(value: unknown): number[] {
  const text = `${value ?? ""}`.trim();
  if (!text) {
    return [];
  }

  return text
    .split(/[^\d]+/)
    .filter(Boolean)
    .map((v) => Number(v))
    .filter((n) => Number.isInteger(n) && n >= 1 && n <= 49);
}

function extractIssueNo(row: OfficialRow): string | null {
  const candidates = [row.issueNo, row.drawNo, row.draw, row.issue, row.no, row.period, row.id];
  for (const c of candidates) {
    const text = `${c ?? ""}`.trim();
    if (/^\d{2}\/\d{3}$/.test(text)) {
      return text;
    }
  }
  return null;
}

function extractDate(row: OfficialRow): Date | null {
  const candidates = [row.date, row.drawDate, row.draw_date, row.drawdate, row.dt];
  for (const c of candidates) {
    const d = parseDate(c);
    if (d) {
      return d;
    }
  }
  return null;
}

function extractNumbers(row: OfficialRow): number[] {
  const nFields = [row.n1, row.n2, row.n3, row.n4, row.n5, row.n6, row.no1, row.no2, row.no3, row.no4, row.no5, row.no6]
    .map(toInt)
    .filter((n): n is number => n !== null && n >= 1 && n <= 49);

  if (nFields.length >= 6) {
    return nFields.slice(0, 6);
  }

  const listFields = [row.numbers, row.nos, row.no, row.result, row.main];
  for (const lf of listFields) {
    const nums = parseNumberList(lf);
    if (nums.length >= 6) {
      return nums.slice(0, 6);
    }
  }

  return [];
}

function extractSpecial(row: OfficialRow): number | null {
  const candidates = [row.specialNumber, row.special, row.sno, row.sn, row.bonus, row.extra, row.n7, row.no7];
  for (const c of candidates) {
    const n = toInt(c);
    if (n !== null && n >= 1 && n <= 49) {
      return n;
    }
  }

  const resultLike = [row.result, row.no, row.numbers].map(parseNumberList).find((arr) => arr.length >= 7);
  if (resultLike) {
    return resultLike[6] ?? null;
  }

  return null;
}

function normalizeOfficialRows(payload: unknown): OfficialRow[] {
  if (Array.isArray(payload)) {
    return payload.filter((v): v is OfficialRow => typeof v === "object" && v !== null);
  }

  if (typeof payload === "object" && payload !== null) {
    const p = payload as Record<string, unknown>;
    const candidates = [p.data, p.results, p.rows, p.items, p.draws, p.list];
    for (const c of candidates) {
      if (Array.isArray(c)) {
        return c.filter((v): v is OfficialRow => typeof v === "object" && v !== null);
      }
    }
  }

  return [];
}

export async function loadOfficialRecords(): Promise<CsvDrawRecord[]> {
  const url =
    process.env.OFFICIAL_RESULT_URL?.trim() ||
    "https://bet.hkjc.com/contentserver/jcbw/cmc/last30draw.json";

  const response = await fetch(url, {
    cache: "no-store",
    headers: {
      "user-agent": "Mozilla/5.0 (compatible; marksix-predictor/1.0)",
      accept: "application/json,text/plain,*/*",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch OFFICIAL_RESULT_URL: ${response.status}`);
  }

  const raw = await response.text();
  const parsed = JSON.parse(raw.replace(/^\uFEFF/, ""));
  const rows = normalizeOfficialRows(parsed);

  const out: CsvDrawRecord[] = [];
  for (const row of rows) {
    const issueNo = extractIssueNo(row);
    const drawDate = extractDate(row);
    const numbers = extractNumbers(row);
    const specialNumber = extractSpecial(row);

    if (!issueNo || !drawDate || numbers.length !== 6 || specialNumber === null) {
      continue;
    }

    out.push({ issueNo, drawDate, numbers, specialNumber });
  }

  if (out.length === 0) {
    throw new Error("Official source parsed 0 records. Please verify OFFICIAL_RESULT_URL format.");
  }

  return out.sort((a, b) => a.drawDate.getTime() - b.drawDate.getTime());
}
