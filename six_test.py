import csv
from collections import Counter

def is_all_odd(nums):
    return all(n % 2 == 1 for n in nums)

def is_all_even(nums):
    return all(n % 2 == 0 for n in nums)

def balance_parity(selected, reserves):
    # selected: list of 6 nums, reserves: list of remaining 2
    if not (is_all_odd(selected) or is_all_even(selected)):
        return selected  # already balanced

    if is_all_odd(selected):
        # Find even in reserves
        evens = [n for n in reserves if n % 2 == 0]
        if evens:
            # Replace the last odd with the first even
            selected[-1] = evens[0]
            return selected

    if is_all_even(selected):
        # Find odd in reserves
        odds = [n for n in reserves if n % 2 == 1]
        if odds:
            # Replace the last even with the first odd
            selected[-1] = odds[0]
            return selected

    # If cannot balance, return original
    return selected

def main():
    ordinary_counter = Counter()
    special_counter = Counter()

    with open('six.csv', 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)  # Skip header
        for row in reader:
            winning_str = row[2].strip('"')
            winning = [int(x) for x in winning_str.split(',')]
            special = int(row[3])
            ordinary_counter.update(winning)
            special_counter[special] += 1

    # Hot rule
    ordinary_hot_all = [num for num, _ in ordinary_counter.most_common(8)]
    special_hot_all = [num for num, _ in special_counter.most_common(2)]

    ordinary_hot_selected = ordinary_hot_all[:6]
    reserves = ordinary_hot_all[6:]
    ordinary_hot_balanced = balance_parity(ordinary_hot_selected, reserves)
    special_hot = special_hot_all[0] if special_hot_all else None

    print("热门规则生成的号码:")
    print("普通号:", sorted(ordinary_hot_balanced))
    print("特别号:", special_hot)
    print()

    # Cold rule
    ordinary_cold_items = sorted(ordinary_counter.items(), key=lambda x: (x[1], x[0]))
    ordinary_cold_all = [num for num, _ in ordinary_cold_items[:8]]
    special_cold_items = sorted(special_counter.items(), key=lambda x: (x[1], x[0]))
    special_cold_all = [num for num, _ in special_cold_items[:2]]

    ordinary_cold_selected = ordinary_cold_all[:6]
    reserves = ordinary_cold_all[6:]
    ordinary_cold_balanced = balance_parity(ordinary_cold_selected, reserves)
    special_cold = special_cold_all[0] if special_cold_all else None

    print("冷门规则生成的号码:")
    print("普通号:", sorted(ordinary_cold_balanced))
    print("特别号:", special_cold)
    print()

    # For odd-even balance rule, generate a simple balanced set using mixed from hot and cold
    # For example, select 3 odd and 3 even from all appeared ordinary numbers
    all_ordinary_nums = list(ordinary_counter.keys())
    odds = [n for n in all_ordinary_nums if n % 2 == 1]
    evens = [n for n in all_ordinary_nums if n % 2 == 0]
    # Take first 3 odds and 3 evens, sort
    balanced_ordinary = sorted(odds[:3] + evens[:3])
    # Special from all special, take one
    all_special_nums = list(special_counter.keys())
    balanced_special = sorted(all_special_nums)[0] if all_special_nums else None

    print("奇偶数平衡规则生成的号码 (使用历史出现号码的奇偶混合):")
    print("普通号:", balanced_ordinary)
    print("特别号:", balanced_special)

if __name__ == "__main__":
    main()
