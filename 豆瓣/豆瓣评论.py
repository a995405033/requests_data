
import requests
from bs4 import BeautifulSoup
import csv
import time
import os
from urllib.parse import urlparse, parse_qs, urljoin

# =====================================================================
# 【必填】把你浏览器里的 Cookie 粘贴到下面，否则豆瓣会返回空页面
# 获取方式：浏览器打开豆瓣 → F12 → Network → 刷新页面 → 点第一个请求
#          → Headers → 找到 Cookie 字段，整行复制过来
# =====================================================================
COOKIE = 'bid=aLlpbkr94PY; _pk_id.100001.4cf6=78d98bb7b14189a7.1772352483.; ap_v=0,6.0; __utmc=30149280; __utmc=223695111; ll="118200"; _vwo_uuid_v2=D61D7EDEB1A9F5B6E71F8485FD981D666|46b6c742346552acde9379e5e9e1ef10; __yadk_uid=AsyKrWDKGaEUARvOkgN80MFuIUrbNAb4; _pk_ref.100001.4cf6=%5B%22%22%2C%22%22%2C1772354615%2C%22https%3A%2F%2Fwww.baidu.com%2Flink%3Furl%3DNflqopE4lX0cfnhQ7PRCpDiM5L-DLM0aG_HFaLRSp1aPlWh_2u4HW5uaBu6j73dPC6H4UCqltFzdmpO-_hWx3q%26wd%3D%26eqid%3Df7366a8a001a30df0000000669a3f3e0%22%5D; _pk_ses.100001.4cf6=1; dbcl2="156663821:5B0dRR5Uuqw"; ck=iG4l; __utma=30149280.115644398.1772352483.1772352483.1772354628.2; __utmb=30149280.0.10.1772354628; __utmz=30149280.1772354628.2.2.utmcsr=open.weixin.qq.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utma=223695111.1091301666.1772352483.1772352483.1772354628.2; __utmb=223695111.0.10.1772354628; __utmz=223695111.1772354628.2.2.utmcsr=open.weixin.qq.com|utmccn=(referral)|utmcmd=referral|utmcct=/; push_noty_num=0; push_doumail_num=0'

STAR_MAP = {
    "allstar50": "5星-力荐",
    "allstar40": "4星-推荐",
    "allstar30": "3星-还行",
    "allstar20": "2星-较差",
    "allstar10": "1星-很差",
}


def _build_headers(url):
    """根据 URL 构造请求头"""
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if COOKIE:
        headers["Cookie"] = COOKIE
    return headers


def _parse_rating(comment_info):
    """从 comment-info 中提取评分"""
    rating_span = comment_info.select_one("span[class*='allstar']")
    if rating_span:
        for cls in rating_span.get("class", []):
            if cls in STAR_MAP:
                return STAR_MAP[cls]
    return "未评分"


def _parse_base_url(url):
    """从完整 URL 中提取基础路径和原始查询参数"""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    params = parse_qs(parsed.query)
    sort = params.get("sort", ["new_score"])[0]
    status = params.get("status", ["P"])[0]
    return base, sort, status


def _fetch_one_page(base_url, headers, start, limit, sort, status):
    """请求单页评论并解析，返回评论列表"""
    params = {"start": start, "limit": limit, "status": status, "sort": sort}
    resp = requests.get(base_url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("div.comment-item")

    if not items:
        print(f"  [调试] 页面长度={len(resp.text)}, 含登录提示={'登录' in resp.text}")

    comments = []
    for item in items:
        avatar_tag = item.select_one("div.avatar a")
        user_url = avatar_tag["href"] if avatar_tag else ""

        info = item.select_one("span.comment-info")
        if not info:
            continue

        username_tag = info.find("a")
        username = username_tag.get_text(strip=True) if username_tag else "匿名"

        rating = _parse_rating(info)

        time_tag = info.select_one("span.comment-time")
        comment_time = time_tag.get("title", "").strip() if time_tag else ""
        if not comment_time:
            comment_time = time_tag.get_text(strip=True) if time_tag else ""

        location_tag = info.select_one("span.comment-location")
        location = location_tag.get_text(strip=True) if location_tag else ""

        content_tag = item.select_one("span.short")
        content = content_tag.get_text(strip=True) if content_tag else ""

        votes_tag = item.select_one("span.vote-count")
        votes = votes_tag.get_text(strip=True) if votes_tag else "0"

        comments.append({
            "用户名": username,
            "用户主页": user_url,
            "评分": rating,
            "评论时间": comment_time,
            "地区": location,
            "有用数": votes,
            "评论内容": content,
        })

    return comments


def crawl_douban_comments(url, max_pages=10, output_csv=None):
    """
    爬取豆瓣电影短评并保存为 CSV。

    参数:
        url       : 豆瓣短评页面链接，如
                    https://movie.douban.com/subject/34780991/comments?start=0&limit=20&status=P&sort=new_score
        max_pages : 最多爬取页数，每页 20 条（默认 10 页 = 200 条）
        output_csv: 保存路径，默认为当前目录下 douban_comments.csv
    """
    if not COOKIE:
        print("=" * 60)
        print("⚠ 未设置 Cookie！豆瓣评论页必须登录才能访问。")
        print("请打开浏览器登录豆瓣，然后 F12 → Network → 复制 Cookie")
        print("粘贴到脚本顶部 COOKIE = \"\" 里面")
        print("=" * 60)
        print()

    base_url, sort, status = _parse_base_url(url)
    headers = _build_headers(url)

    if output_csv is None:
        output_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "douban_comments.csv")

    print(f"目标: {base_url}")
    print(f"排序: {sort} | 状态: {status} | 计划爬取: {max_pages} 页")
    print("-" * 60)

    all_comments = []

    for page in range(max_pages):
        start = page * 20
        print(f"正在请求第 {page + 1}/{max_pages} 页 (start={start}) ...")

        try:
            comments = _fetch_one_page(base_url, headers, start, 20, sort, status)
        except requests.HTTPError as e:
            print(f"请求失败 (HTTP {e.response.status_code}): {e}")
            if e.response.status_code == 403:
                print("→ 被豆瓣反爬拦截，请检查 Cookie 是否有效")
            break
        except Exception as e:
            print(f"请求异常: {e}")
            break

        if not comments:
            print("该页无评论，爬取结束")
            break

        all_comments.extend(comments)
        print(f"  获取 {len(comments)} 条，累计 {len(all_comments)} 条")

        for c in comments:
            print(f"  [{c['评分']}] {c['用户名']}({c['地区']}): {c['评论内容'][:50]}...")

        time.sleep(2 + page * 0.5)

    # 保存 CSV
    if not all_comments:
        print("没有评论数据可保存")
        return all_comments

    fieldnames = ["用户名", "用户主页", "评分", "评论时间", "地区", "有用数", "评论内容"]
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_comments)

    print(f"\n已保存 {len(all_comments)} 条评论 → {output_csv}")
    print("完成！")
    return all_comments


if __name__ == "__main__":
    crawl_douban_comments(
        url="https://movie.douban.com/subject/34780991/comments?start=0&limit=20&status=P&sort=new_score",
        max_pages=40,
        output_csv="douban_comments.csv",
    )

