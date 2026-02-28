import { parseDrawCsv, readLocalCsv } from "@/lib/csv";
import { loadOfficialRecords } from "@/lib/official-source";
import { type CsvDrawRecord } from "@/lib/types";

export async function loadDrawRecords(): Promise<CsvDrawRecord[]> {
  const provider = (process.env.RESULT_PROVIDER || "").trim().toLowerCase();
  const officialRequired = (process.env.OFFICIAL_SOURCE_REQUIRED || "").trim() === "true";

  if (provider === "official") {
    return loadOfficialRecords();
  }

  if (provider === "csv") {
    const remoteCsv = process.env.RESULT_CSV_URL?.trim();
    if (remoteCsv) {
      const response = await fetch(remoteCsv, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Failed to fetch RESULT_CSV_URL: ${response.status}`);
      }
      const raw = await response.text();
      return parseDrawCsv(raw);
    }

    const localPath = process.env.LOCAL_RESULT_CSV_PATH?.trim() || "./Mark_Six.csv";
    return parseDrawCsv(readLocalCsv(localPath));
  }

  try {
    return await loadOfficialRecords();
  } catch (error) {
    if (officialRequired) {
      throw error;
    }
  }

  const remote = process.env.RESULT_CSV_URL?.trim();

  if (remote) {
    const response = await fetch(remote, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to fetch RESULT_CSV_URL: ${response.status}`);
    }
    const raw = await response.text();
    return parseDrawCsv(raw);
  }

  const localPath = process.env.LOCAL_RESULT_CSV_PATH?.trim() || "./Mark_Six.csv";
  return parseDrawCsv(readLocalCsv(localPath));
}
