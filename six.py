import requests
from bs4 import BeautifulSoup
import csv

# 函数：计算统计列
def calculate_stats(numbers, prev_numbers):
    # numbers: list of 6 int red balls, sorted
    # prev_numbers: list from previous C column
    common_list = sorted([n for n in numbers if n in prev_numbers])  # 上期出现号码 (joined if multiple)
    common_str = ','.join(map(str, common_list)) if common_list else ''
    small = len([n for n in numbers if n <= 24])  # 小
    big = 6 - small  # 大
    odd = len([n for n in numbers if n % 2 == 1])  # 单数
    even = 6 - odd  # 双数
    c1_10 = len([n for n in numbers if 1 <= n <= 10])  # 1-10
    c11_20 = len([n for n in numbers if 11 <= n <= 20])  # 11-20
    c21_30 = len([n for n in numbers if 21 <= n <= 30])  # 21-30
    c31_40 = len([n for n in numbers if 31 <= n <= 40])  # 31-40
    c41_50 = len([n for n in numbers if 41 <= n <= 50])  # 41-50
    return [common_str, small, big, odd, even, c1_10, c11_20, c21_30, c31_40, c41_50, c1_10, c11_20, c21_30, c31_40, c41_50]

# 读取六合彩现在的历史搅珠数据
csv_filename = 'six.csv'
header = ['期号', '日期', '中奖号码', '特别号码', '上期出现号码', '小', '大', '单数', '双数', '1-10', '11-20', '21-30', '31-40', '41-50', '1-10', '11-20', '21-30', '31-40', '41-50']

data_rows = []
try:
    with open(csv_filename, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # 跳过header
        data_rows = list(reader)
except FileNotFoundError:
    print(f"{csv_filename} 不存在，将创建新文件。")
    data_rows = []

# 获取当前最新期号和上期号码
current_period = data_rows[0][0] if data_rows else '25/000'
prev_numbers_str = data_rows[0][2].strip('"') if data_rows else ''
prev_numbers = [int(n) for n in prev_numbers_str.split(',')] if prev_numbers_str else []

# 抓取网站
url = 'https://www.cpzhan.com/liu-he-cai/all-results'
response = requests.get(url)
soup = BeautifulSoup(response.text, 'html.parser')
rows = soup.find_all('tr')[1:]
new_entries = []  # 存储新数据 [period_num, period, date_str, numbers, numbers_joined, special]

for row in rows:
    cols = row.find_all('td')
    if len(cols) != 10: continue  # 确保10列
    year = cols[0].text.strip()
    period_num = cols[1].text.strip()
    date_str = cols[2].text.strip()
    numbers_str = [cols[i].text.strip() for i in range(3, 9)]
    special = cols[9].text.strip()
    
    # 构建期号如 '25/105'
    period = f"{year[2:]}/{period_num}"
    
    # 过滤数字并排序
    numbers = sorted([int(n) for n in numbers_str if n.isdigit()])
    numbers_joined = ','.join(map(str, numbers))
    
    # 如果这个期号 > 当前最新，添加（假设同年前缀）
    current_num = int(current_period.split('/')[1]) if '/' in current_period else 0
    if int(period_num) > current_num:
        new_entries.append([int(period_num), period, date_str, numbers, numbers_joined, special])

if new_entries:
    # 按期号升序排序
    new_entries.sort(key=lambda x: x[0])
    
    new_rows = []
    current_prev = prev_numbers
    for entry in new_entries:
        period_num, period, date_str, numbers, numbers_joined, special = entry
        stats = calculate_stats(numbers, current_prev)
        row = [period, date_str, numbers_joined, special] + stats
        new_rows.append(row)
        current_prev = numbers  # 更新为当前号码，用于下一个新期
    
    # new_rows
    new_rows.reverse()
    
    # 更新 data_rows
    data_rows = new_rows + data_rows
    
    # 写入CSV
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in data_rows:
            writer.writerow(row)
    
    print("发现新数据！已添加到 six.csv 的顶部。")
else:
    print("没有新数据。最新期仍是", current_period)
