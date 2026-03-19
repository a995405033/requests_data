import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.chinanews.com.cn"
LIST_URL = f"{BASE_URL}/scroll-news/news1.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
}


def get_news_list() -> list[dict]:
    """请求滚动新闻列表页，返回 [{"title", "time", "url"}] 列表"""
    resp = requests.get(LIST_URL, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    news_items = []
    for li in soup.find_all("li"):
        bt_div = li.find("div", class_="dd_bt")
        time_div = li.find("div", class_="dd_time")
        lm_div = li.find("div", class_="dd_lm")
        if not bt_div or not time_div:
            continue
        # 跳过视频类新闻
        if lm_div and "视频" in lm_div.get_text():
            continue
        a_tag = bt_div.find("a")
        if not a_tag:
            continue
        href = a_tag["href"]
        # 相对路径补全为绝对路径
        if href.startswith("/"):
            href = BASE_URL + href
        news_items.append({
            "title": a_tag.get_text(strip=True),
            "time": time_div.get_text(strip=True),
            "url": href,
        })
    return news_items


def get_news_detail(url: str) -> dict:
    """请求新闻详情页，返回 {"title", "time", "content"} 字典"""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 标题
    title_tag = soup.select_one("h1.content_left_title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # 发布时间（优先读隐藏的百度蜘蛛字段，格式更精确）
    pub_time_tag = soup.select_one("#pubtime_baidu")
    if pub_time_tag:
        pub_time = pub_time_tag.get_text(strip=True)
    else:
        time_div = soup.select_one("div.content_left_time")
        pub_time = time_div.get_text(" ", strip=True).split("来源")[0].strip() if time_div else ""

    # 正文文本（仅提取 <p> 段落文字）
    content_div = soup.select_one("div.left_zw")
    paragraphs = []
    if content_div:
        for p in content_div.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                paragraphs.append(text)
    content = "\n".join(paragraphs)

    return {"title": title, "time": pub_time, "content": content}


if __name__ == "__main__":
    print("=== 获取新闻列表 ===")
    news_list = get_news_list()
    print(f"共获取 {len(news_list)} 条新闻\n")
    for i, item in enumerate(news_list[:5], 1):
        print(f"{i}. [{item['time']}] {item['title']}")
        print(f"   URL: {item['url']}")

    for i, target in enumerate(news_list[:3], 1):
        print(f"\n=== 详情 {i}：{target['title']} ===")
        detail = get_news_detail(target["url"])
        print(f"标题：{detail['title']}")
        print(f"时间：{detail['time']}")
        print(f"正文：\n{detail['content']}")
        print("-" * 60)
