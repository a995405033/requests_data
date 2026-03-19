import time
import json
import random
import os
import requests
import base64
from lxml import etree
from datetime import datetime
from Crypto.Cipher import AES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; WOW64)",
    "Mozilla/5.0 (Windows NT 6.3; WOW64)",
    "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11",
    "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; rv:11.0) like Gecko",
    "Mozilla/5.0 (Windows NT 5.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.95 Safari/537.36",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
]


def random_ua():
    return random.choice(USER_AGENTS)


# ==================== AES 加密相关 ====================

def generate_crypte(city):
    """逆向加密 KEY 破解，生成请求所需的 crypte 参数"""
    current_time = datetime.now()
    time_string = current_time.strftime("%Y%m%d%H%M%S")
    data = f"{city}_{time_string}".encode('utf-8')
    key = "5ha5Z7cZ3WNbD3rA".encode('utf-8')
    iv = "AYk98XaiBwCi0Dst".encode('utf-8')
    cipher = AES.new(key, AES.MODE_CBC, iv)
    pad_len = 16 - (len(data) % 16)
    padded_data = data + bytes([pad_len]) * pad_len
    encrypted_data = cipher.encrypt(padded_data)
    crypte = base64.b64encode(encrypted_data).decode('utf-8')
    return crypte


def get_weather_data(raw_url, city):
    """通过加密接口获取某城市某月的天气数据（JSON）"""
    crypte = generate_crypte(city)
    parts = raw_url.split('/')
    yearmonth_html = parts[-1]
    yearmonth = yearmonth_html.split('.')[0]

    request_url = f"https://lishi.tianqi.com/monthdata/{city}/{yearmonth}"
    headers = {
        'Referer': raw_url,
        'User-Agent': random_ua(),
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    data = {'crypte': crypte}

    response = requests.post(request_url, data=data, headers=headers)
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        return []


# ==================== 爬取城市列表 ====================

def crawl_city_list(save_path=None):
    """
    爬取天气网站所有城市名称和对应 URL，保存到 JSON 文件。

    返回: dict，格式 {城市名: url, ...}
    """
    if save_path is None:
        save_path = os.path.join(BASE_DIR, "city_list.json")

    session = requests.Session()
    headers = {'User-Agent': random_ua()}
    page = session.get(url='https://lishi.tianqi.com/', headers=headers)
    tree = etree.HTML(page.text)

    city_dict = {}
    for row in range(2, 25):
        li_list = tree.xpath(f"/html/body/div[10]/div[4]/table/tbody/tr[{row}]/td/ul/li")
        for li in li_list:
            try:
                name = li.xpath("./a/text()")[0]
                url = "https://lishi.tianqi.com/" + str(li.xpath("./a/@href")[0]).replace("/index.html", "")
                city_dict[name] = url
                print(f"{name} -> {url}")
            except Exception:
                pass

    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(city_dict, f, ensure_ascii=False, indent=2)

    print(f"\n共获取 {len(city_dict)} 个城市，已保存到 {save_path}")
    return city_dict


def load_city_list(path=None):
    """从 JSON 文件读取城市列表"""
    if path is None:
        path = os.path.join(BASE_DIR, "city_list.json")
    if not os.path.exists(path):
        print("城市列表文件不存在，请先执行 crawl_city_list()")
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==================== 按城市爬取天气数据 ====================

# API 返回字段 → 中文名称映射
FIELD_CN = {
    "date_str": "日期",
    "week":     "星期",
    "weather":  "天气",
    "htemp":    "最高气温",
    "ltemp":    "最低气温",
    "WD":       "风向",
    "WS":       "风力",
    "aqi":      "空气质量指数",
    "pm25":     "PM2.5",
}


def print_daily(record):
    """用中文标签打印一条逐日天气数据"""
    parts = [
        f"日期：{record['日期']}",
        f"星期：{record['星期']}",
        f"天气：{record['天气']}",
        f"最高气温：{record['最高气温']}",
        f"最低气温：{record['最低气温']}",
        f"风向：{record['风向']}",
        f"风力：{record['风力']}",
        f"空气质量指数：{record['空气质量指数']}",
        f"PM2.5：{record['PM2.5']}",
    ]
    print("  " + " | ".join(parts))


def print_monthly(record):
    """用中文标签打印一条月均数据"""
    parts = [
        f"月份：{record['月份']}",
        f"城市：{record['城市']}",
        f"平均高温：{record['平均高温']}℃",
        f"平均低温：{record['平均低温']}℃",
        f"极端高温：{record['极端高温']}℃",
        f"极端低温：{record['极端低温']}℃",
        f"空气指数：{record['空气指数']}",
        f"空气最好：{record['空气最好']}",
        f"空气最差：{record['空气最差']}",
    ]
    print("  " + " | ".join(parts))


def _build_month_list(start_year, end_year, end_month):
    """生成需要爬取的年月列表，如 ['202401', '202402', ...]"""
    result = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            ym = f"{year}{month:02d}"
            if ym == end_month:
                return result
            result.append(ym)
    return result


def _parse_xpath_daily(tree, city_name):
    """从页面 HTML 解析逐日数据（XPath 方式，通常为每月前 10 天）"""
    records = []
    li_list = tree.xpath('/html/body/div[7]/div[1]/div[4]/ul/li')
    for li in li_list:
        try:
            raw_text = str(li.xpath('./div[1]/text()')[0])
            date = raw_text.split(" ")[0]
            week = raw_text.split(" ")[1]
            records.append({
                "日期": date,
                "星期": week,
                "城市": city_name,
                "最高气温": li.xpath('./div[2]/text()')[0],
                "最低气温": li.xpath('./div[3]/text()')[0],
                "天气": li.xpath('./div[4]/text()')[0],
                "风向": li.xpath('./div[5]/text()')[0],
                "风力": "",
                "空气质量指数": "",
                "PM2.5": "",
            })
        except Exception:
            pass
    return records


def _parse_api_daily(api_data, city_name, existing_dates):
    """从加密接口返回的 JSON 解析逐日数据，跳过已存在的日期"""
    records = []
    if not api_data or not isinstance(api_data, list):
        return records

    for item in api_data:
        try:
            date = item.get("date_str", "")
            if date in existing_dates:
                continue
            records.append({
                "日期": date,
                "星期": item.get("week", ""),
                "城市": city_name,
                "最高气温": f"{item.get('htemp', '')}℃",
                "最低气温": f"{item.get('ltemp', '')}℃",
                "天气": item.get("weather", ""),
                "风向": item.get("WD", ""),
                "风力": item.get("WS", ""),
                "空气质量指数": str(item.get("aqi", "")),
                "PM2.5": str(item.get("pm25", "")),
            })
        except Exception as e:
            print(f"  解析单日数据出错: {e}")
    return records


def _parse_xpath_monthly(tree, yearmonth, city_name):
    """从页面 HTML 解析月均汇总数据"""
    base = '/html/body/div[7]/div[1]/div[3]/ul/li'
    try:
        return {
            "月份": yearmonth,
            "城市": city_name,
            "平均高温": str(tree.xpath(f'{base}[1]/div[1]/div[1]/text()')[0]).replace("℃", ""),
            "平均低温": str(tree.xpath(f'{base}[1]/div[2]/div[1]/text()')[0]).replace("℃", ""),
            "极端高温": str(tree.xpath(f'{base}[2]/div[1]/text()')[0]).replace("℃", ""),
            "极端低温": str(tree.xpath(f'{base}[3]/div[1]/text()')[0]).replace("℃", ""),
            "空气指数": str(tree.xpath(f'{base}[4]/div[1]/text()')[0]),
            "空气最好": str(tree.xpath(f'{base}[5]/div[1]/text()')[0]),
            "空气最差": str(tree.xpath(f'{base}[6]/div[1]/text()')[0]),
        }
    except Exception:
        return None


def crawl_weather_by_city(city_name, city_url=None, start_year=2024, end_year=2025, end_month="202510"):
    """
    输入城市名称，爬取该城市的历史天气数据。

    参数:
        city_name:  城市名称（如 "北京"）
        city_url:   城市对应的 URL，若为 None 则自动从 city_list.json 查找
        start_year: 开始年份
        end_year:   结束年份
        end_month:  终止月份字符串（如 "202510"），到达此月份时停止

    返回:
        dict: {"月均数据": [...], "逐日数据": [...]}
    """
    # ---------- 1. 确认城市 URL ----------
    if city_url is None:
        city_dict = load_city_list()
        city_url = city_dict.get(city_name)
        if not city_url:
            print(f"未找到城市 '{city_name}'，请检查名称或先执行 crawl_city_list()")
            return None

    city_pinyin = city_url.split('/')[-1]
    session = requests.Session()

    monthly_list = []
    daily_list = []

    # ---------- 2. 生成年月列表并逐月爬取 ----------
    month_tasks = _build_month_list(start_year, end_year, end_month)

    for yearmonth in month_tasks:
        page_url = f"{city_url}/{yearmonth}.html"
        print(f"\n{'='*60}")
        print(f"  正在爬取 [{city_name}] {yearmonth[:4]}年{yearmonth[4:]}月")
        print(f"  URL: {page_url}")
        print(f"{'='*60}")

        time.sleep(1)

        # ---------- 3. 请求页面 HTML ----------
        try:
            page = session.get(url=page_url, headers={'User-Agent': random_ua()})
            tree = etree.HTML(page.text)
        except Exception as e:
            print(f"  页面请求失败: {e}")
            continue

        # ---------- 4. 解析月均数据 ----------
        monthly = _parse_xpath_monthly(tree, yearmonth, city_name)
        if monthly:
            monthly_list.append(monthly)
            print(f"\n  --- 月均汇总 ---")
            print_monthly(monthly)

        # ---------- 5. 解析逐日数据（XPath，前 10 天） ----------
        xpath_records = _parse_xpath_daily(tree, city_name)

        # ---------- 6. 解析逐日数据（加密接口，完整月份） ----------
        try:
            api_data = get_weather_data(page_url, city_pinyin)
            existing_dates = {r["日期"] for r in xpath_records}
            api_records = _parse_api_daily(api_data, city_name, existing_dates)
        except Exception as e:
            print(f"  加密接口请求失败: {e}")
            api_records = []

        # ---------- 7. 合并并输出 ----------
        month_records = xpath_records + api_records
        month_records.sort(key=lambda r: r["日期"])

        if month_records:
            print(f"\n  --- 逐日明细（共 {len(month_records)} 天） ---")
            for record in month_records:
                print_daily(record)

        daily_list.extend(month_records)

    # ---------- 8. 汇总结果 ----------
    result = {"月均数据": monthly_list, "逐日数据": daily_list}
    print(f"\n{'='*60}")
    print(f"  爬取完成！月均数据 {len(monthly_list)} 条，逐日数据 {len(daily_list)} 条")
    print(f"{'='*60}")
    return result


def save_weather_data(data, city_name, save_dir=None):
    """将爬取的天气数据保存为 JSON 文件"""
    if save_dir is None:
        save_dir = BASE_DIR
    path = os.path.join(save_dir, f"{city_name}_天气数据.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"数据已保存到 {path}")
    return path


# ==================== 主程序入口 ====================

if __name__ == '__main__':
    print("=" * 50)
    print("  天气历史数据爬取工具")
    print("=" * 50)
    print("1. 爬取城市列表（保存到 city_list.json）")
    print("2. 按城市名称爬取天气数据")
    print("=" * 50)

    choice = input("请选择功能 (1/2): ").strip()

    if choice == "1":
        crawl_city_list()

    elif choice == "2":
        city_dict = load_city_list()
        if not city_dict:
            print("正在先爬取城市列表...")
            city_dict = crawl_city_list()

        city_name = input("请输入城市名称（如 北京）: ").strip()
        if city_name not in city_dict:
            print(f"未找到城市 '{city_name}'，请确认名称正确")
        else:
            data = crawl_weather_by_city(city_name)
            if data:
                save_weather_data(data, city_name)
    else:
        print("无效选择")