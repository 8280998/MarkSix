import { type Draw } from "@prisma/client";
import { type StrategyId, type StrategyResult } from "@/lib/types";

const ALL_NUMBERS = Array.from({ length: 49 }, (_, i) => i + 1);

function decodeNumbers(draw: Draw): number[] {
  return JSON.parse(draw.numbersJson) as number[];
}

function omissionMap(draws: Draw[]): Map<number, number> {
  const omission = new Map<number, number>(ALL_NUMBERS.map((n) => [n, draws.length + 1]));
  for (let idx = 0; idx < draws.length; idx += 1) {
    const nums = decodeNumbers(draws[idx]);
    for (const n of nums) {
      if ((omission.get(n) ?? 9999) > idx + 1) {
        omission.set(n, idx + 1);
      }
    }
  }
  return omission;
}

function frequencyMap(draws: Draw[]): Map<number, number> {
  const freq = new Map<number, number>(ALL_NUMBERS.map((n) => [n, 0]));
  for (const draw of draws) {
    for (const n of decodeNumbers(draw)) {
      freq.set(n, (freq.get(n) ?? 0) + 1);
    }
  }
  return freq;
}

function weightedRecencyMap(draws: Draw[]): Map<number, number> {
  const weighted = new Map<number, number>(ALL_NUMBERS.map((n) => [n, 0]));
  for (let i = 0; i < draws.length; i += 1) {
    const draw = draws[i];
    const weight = 1 / (1 + i);
    for (const n of decodeNumbers(draw)) {
      weighted.set(n, (weighted.get(n) ?? 0) + weight);
    }
  }
  return weighted;
}

function normalize(map: Map<number, number>): Map<number, number> {
  const values = [...map.values()];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return new Map([...map.entries()].map(([k, v]) => [k, (v - min) / range]));
}

function pickTopSix(scores: Map<number, number>, reasonPrefix: string): StrategyResult["picks"] {
  const sorted = [...scores.entries()].sort((a, b) => b[1] - a[1]);
  const selected: Array<[number, number]> = [];

  for (const item of sorted) {
    if (selected.length === 6) {
      break;
    }

    const candidate = item[0];
    const next = [...selected, item].map(([n]) => n);
    const oddCount = next.filter((n) => n % 2 === 1).length;

    if (next.length >= 4 && (oddCount === 0 || oddCount === next.length)) {
      continue;
    }
    selected.push(item);
  }

  while (selected.length < 6) {
    const fallback = sorted.find(([n]) => !selected.some(([picked]) => picked === n));
    if (!fallback) {
      break;
    }
    selected.push(fallback);
  }

  return selected.map(([number, score], index) => ({
    number,
    rank: index + 1,
    score,
    reason: `${reasonPrefix} score=${score.toFixed(4)}`,
  }));
}

export const strategyMeta: Record<StrategyId, { name: string; description: string }> = {
  balanced_v1: {
    name: "组合策略 v1（默认）",
    description: "热号 + 冷号回补 + 近期动量的加权组合",
  },
  hot_v1: {
    name: "热号策略 v1",
    description: "优先选择近期开奖高频号码",
  },
  cold_rebound_v1: {
    name: "冷号回补 v1",
    description: "优先选择长遗漏号码",
  },
  momentum_v1: {
    name: "近期动量 v1",
    description: "优先选择最近几期权重更高的号码",
  },
};

export function generateStrategyResult(strategy: StrategyId, recentDraws: Draw[]): StrategyResult {
  const window = recentDraws.slice(0, Math.min(80, recentDraws.length));
  const freq = normalize(frequencyMap(window));
  const omission = normalize(omissionMap(window));
  const momentum = normalize(weightedRecencyMap(window));

  const composite = new Map<number, number>();
  for (const n of ALL_NUMBERS) {
    const f = freq.get(n) ?? 0;
    const o = omission.get(n) ?? 0;
    const m = momentum.get(n) ?? 0;

    let score = 0;
    if (strategy === "hot_v1") {
      score = f * 0.8 + m * 0.2;
    } else if (strategy === "cold_rebound_v1") {
      score = o * 0.7 + m * 0.3;
    } else if (strategy === "momentum_v1") {
      score = m * 0.9 + f * 0.1;
    } else {
      score = f * 0.45 + o * 0.35 + m * 0.2;
    }

    composite.set(n, score);
  }

  return {
    strategy,
    strategyVersion: strategy,
    picks: pickTopSix(composite, strategyMeta[strategy].name),
  };
}

export function allStrategies(): StrategyId[] {
  return ["balanced_v1", "hot_v1", "cold_rebound_v1", "momentum_v1"];
}
