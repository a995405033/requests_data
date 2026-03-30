"""
B站关键词搜索 - DrissionPage 打开搜索页获取 Cookie/qv_id，
再用 WBI 签名请求官方接口分页（与网页一致）：
  第 1 页: /x/web-interface/wbi/search/all/v2
  第 2 页起: /x/web-interface/wbi/search/type (search_type=video, dynamic_offset)
"""
from DrissionPage import ChromiumPage
from time import sleep
from datetime import datetime
import re
import csv
import os
import hashlib
import time
import urllib.parse

# 优先 curl_cffi（与榜单脚本一致，利于过风控）
try:
    from curl_cffi import requests as http_client
    USE_CURL_CFFI = True
    IMPERSONATE = "chrome124"
except ImportError:
    import requests as http_client
    USE_CURL_CFFI = False
    IMPERSONATE = None

PAGE_SIZE = 42

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://search.bilibili.com/",
    "Origin": "https://search.bilibili.com",
}

JS_QVID = r"""
(function(){
  try {
    const pinia = window.__pinia;
    if (!pinia) return "";
    const s = JSON.stringify(pinia);
    const m = s.match(/"qv_id"\s*:\s*"([^"]+)"/);
    if (m) return m[1];
    const sr = pinia.searchResponse;
    if (sr && typeof sr.qv_id === 'string') return sr.qv_id;
    return "";
  } catch(e) { return ""; }
})()
"""


def clean_html(text):
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def format_number(n):
    if not isinstance(n, (int, float)):
        return str(n)
    if n >= 100000000:
        return f"{n / 100000000:.1f}亿"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def page_cookies_dict(page):
    """从浏览器取出全部 Cookie，供 requests 使用（含 HttpOnly）"""
    raw = page.cookies(all_domains=True)
    return {c["name"]: c["value"] for c in raw}


def _http_get(url, cookies, params=None):
    kw = {"headers": HEADERS, "cookies": cookies, "timeout": 30}
    if params is not None:
        kw["params"] = params
    if USE_CURL_CFFI and IMPERSONATE:
        kw["impersonate"] = IMPERSONATE
    return http_client.get(url, **kw)


def get_wbi_keys(cookies):
    r = _http_get("https://api.bilibili.com/x/web-interface/nav", cookies)
    r.raise_for_status()
    data = r.json()
    wbi_img = data.get("data", {}).get("wbi_img", {})
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0] if img_url else ""
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0] if sub_url else ""
    return img_key, sub_key


def get_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB if i < len(orig))[:32]


def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    mixin_key = get_mixin_key(img_key + sub_key)
    params = {**params, "wts": round(time.time())}
    params = dict(sorted(params.items()))
    params = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params


def normalize_video_item(v: dict) -> dict:
    """统一成与原先 CSV 一致的字段名"""
    if not v:
        return {}
    if "arc" in v and isinstance(v["arc"], dict):
        v = {**v["arc"], **{k: v[k] for k in v if k != "arc"}}
    out = dict(v)
    if out.get("danmaku") in (None, 0) and out.get("video_review") is not None:
        out["danmaku"] = out["video_review"]
    if out.get("review") in (None, 0) and out.get("video_review") is not None:
        out["review"] = out.get("review") or 0
    return out


def extract_videos_from_api_data(data: dict) -> list:
    """解析 search/all/v2 与 search/type 的 data 字段"""
    videos = []
    result = data.get("result")
    if not result:
        return videos

    for group in result:
        if not isinstance(group, dict):
            continue
        inner = group.get("data")
        if isinstance(inner, list):
            for item in inner:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "video" or item.get("result_type") == "video":
                    videos.append(normalize_video_item(item))
                elif "bvid" in item:
                    videos.append(normalize_video_item(item))
        elif group.get("type") == "video" or group.get("result_type") == "video":
            videos.append(normalize_video_item(group))
        elif "bvid" in group:
            videos.append(normalize_video_item(group))

    # 兜底：结构变化时从 result 树里收集带 bvid 的条目（去重）
    if not videos:
        seen = set()

        def collect(obj):
            if isinstance(obj, dict):
                bv = obj.get("bvid")
                if bv and bv not in seen:
                    seen.add(bv)
                    videos.append(normalize_video_item(obj))
                for v in obj.values():
                    collect(v)
            elif isinstance(obj, list):
                for x in obj:
                    collect(x)

        collect(result)
    return videos


def parse_search_api_response(j: dict, ctx: dict = None) -> tuple:
    """
    返回 (data_dict, error_message)
    data_dict 含 numResults, page, pagesize, numPages, videos
    """
    if j.get("code") != 0:
        return None, j.get("message", f"code={j.get('code')}")

    data = j.get("data") or {}
    if not isinstance(data, dict):
        return None, "data 格式异常"

    if ctx is not None:
        qv = data.get("qv_id")
        if qv:
            ctx["qv_id"] = str(qv)

    if "v_voucher" in data and len(data) <= 2:
        return None, "触发风控/验证码(v_voucher)，请在已登录的浏览器里重试或稍后再试"

    videos = extract_videos_from_api_data(data)
    return {
        "numResults": data.get("numResults") or data.get("numresults") or 0,
        "page": data.get("page") or 1,
        "pagesize": data.get("pagesize") or PAGE_SIZE,
        "numPages": data.get("numPages") or data.get("numpages") or 1,
        "videos": videos,
    }, None


def build_search_params(keyword: str, page_num: int, qv_id: str) -> tuple:
    """
    返回 (url, params_dict_before_wbi)
    第 1 页 all/v2；第 2 页起 type + dynamic_offset
    """
    common_kw = {
        "keyword": keyword,
        "qv_id": qv_id or "",
        "from_spmid": "333.337",
        "platform": "pc",
        "highlight": 1,
        "single_column": 0,
        "pubtime_begin_s": 0,
        "pubtime_end_s": 0,
        "web_roll_page": 1,
        "web_location": 1430654,
        "source_tag": 3,
    }

    if page_num == 1:
        url = "https://api.bilibili.com/x/web-interface/wbi/search/all/v2"
        params = {
            "__refresh__": "true",
            "_extra": "",
            "context": "",
            "page": 1,
            "page_size": PAGE_SIZE,
            "order": "",
            "duration": "",
            "from_source": "",
            "ad_resource": 5646,
            **common_kw,
        }
        return url, params

    url = "https://api.bilibili.com/x/web-interface/wbi/search/type"
    params = {
        "category_id": "",
        "search_type": "video",
        "ad_resource": 5654,
        "__refresh__": "true",
        "_extra": "",
        "context": "",
        "page": page_num,
        "page_size": PAGE_SIZE,
        "from_source": "",
        "gaia_vtoken": "",
        "dynamic_offset": (page_num - 1) * PAGE_SIZE,
        **common_kw,
    }
    return url, params


def fetch_page_via_api(cookies, img_key, sub_key, keyword, page_num, qv_ctx: dict):
    qv_id = qv_ctx.get("qv_id") or ""
    url, base_params = build_search_params(keyword, page_num, qv_id)
    signed = enc_wbi(dict(base_params), img_key, sub_key)
    print(f"\n  正在请求第 {page_num} 页 API: {url.split('/')[-1]} (page={page_num}, offset={(page_num-1)*PAGE_SIZE})")
    r = _http_get(url, cookies, params=signed)
    r.raise_for_status()
    j = r.json()
    data, err = parse_search_api_response(j, ctx=qv_ctx)
    if err:
        print(f"  接口错误: {err}")
        return None
    print(f"  本页获取 {len(data['videos'])} 个视频")
    return data


def print_videos(videos, start_index=0):
    for i, v in enumerate(videos):
        title = clean_html(v.get("title", ""))
        desc = clean_html(v.get("description", ""))
        pic = v.get("pic", "")
        if pic and pic.startswith("//"):
            pic = "https:" + pic

        pubdate = v.get("pubdate", 0)
        pub_time = (
            datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M")
            if pubdate
            else v.get("pubstr", "-")
        )

        idx = start_index + i + 1
        print(f"\n  ── 第 {idx} 条 ──")
        print(f"  标题:     {title}")
        print(f"  BV号:     {v.get('bvid', '-')}")
        print(f"  AV号:     {v.get('aid', '-')}")
        print(f"  UP主:     {v.get('author', '-')} (UID: {v.get('mid', '-')})")
        print(f"  分区:     {v.get('typename', '-')}")
        print(f"  时长:     {v.get('duration', '-')}")
        print(f"  发布时间: {pub_time}")
        print(f"  播放量:   {format_number(v.get('play', 0))}")
        print(f"  点赞:     {format_number(v.get('like', 0))}")
        print(f"  收藏:     {format_number(v.get('favorites', 0))}")
        print(f"  弹幕:     {format_number(v.get('danmaku', 0))}")
        print(f"  评论:     {format_number(v.get('review', 0))}")
        print(f"  标签:     {v.get('tag', '-')}")
        print(f"  简介:     {desc[:80] if desc else '-'}")
        print(f"  封面:     {pic}")


CSV_HEADERS = [
    "序号", "标题", "BV号", "AV号", "UP主", "UID",
    "分区", "时长", "发布时间", "播放量", "点赞",
    "收藏", "弹幕", "评论", "标签", "简介", "封面",
]


def init_csv(keyword):
    filename = f"B站搜索_{keyword}.csv"
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(CSV_HEADERS)
    print(f"  CSV文件已创建: {filepath}")
    return filepath


def append_to_csv(filepath, videos, start_index):
    with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        for i, v in enumerate(videos):
            title = clean_html(v.get("title", ""))
            desc = clean_html(v.get("description", ""))
            pic = v.get("pic", "")
            if pic and pic.startswith("//"):
                pic = "https:" + pic
            pubdate = v.get("pubdate", 0)
            pub_time = (
                datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M")
                if pubdate
                else v.get("pubstr", "-")
            )
            writer.writerow([
                start_index + i + 1,
                title,
                v.get("bvid", ""),
                v.get("aid", ""),
                v.get("author", ""),
                v.get("mid", ""),
                v.get("typename", ""),
                v.get("duration", ""),
                pub_time,
                v.get("play", 0),
                v.get("like", 0),
                v.get("favorites", 0),
                v.get("danmaku", 0),
                v.get("review", 0),
                v.get("tag", ""),
                desc,
                pic,
            ])


def search_bilibili(keyword, pages=1):
    print(f'{"=" * 70}')
    print(f'  B站搜索: "{keyword}"  |  计划爬取 {pages} 页（每页 {PAGE_SIZE} 条，官方接口）')
    print(f'{"=" * 70}')

    browser = ChromiumPage()
    first_url = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(keyword)}"
    print(f"\n  打开搜索页（获取 Cookie / qv_id）: {first_url}")
    browser.get(first_url)
    sleep(5)

    cookies = page_cookies_dict(browser)
    qv_id = (browser.run_js(JS_QVID) or "").strip()
    if qv_id:
        print(f"  已获取 qv_id: {qv_id[:20]}...")
    else:
        print("  未从页面解析到 qv_id，将带空串请求（多数情况下仍可用）")

    try:
        img_key, sub_key = get_wbi_keys(cookies)
    except Exception as e:
        print(f"  获取 WBI 密钥失败: {e}")
        return

    csv_path = init_csv(keyword)
    total_count = 0
    qv_ctx = {"qv_id": qv_id}

    for p in range(1, pages + 1):
        try:
            data = fetch_page_via_api(cookies, img_key, sub_key, keyword, p, qv_ctx)
        except Exception as e:
            print(f"  第 {p} 页请求异常: {e}")
            break

        if not data:
            print(f"  第 {p} 页获取失败，停止（已写入 {total_count} 条）")
            break

        videos = data["videos"]
        if not videos:
            print(f"  第 {p} 页没有视频数据，停止翻页")
            break

        if p == 1:
            total = data["numResults"]
            total_pages = data["numPages"]
            pagesize = data["pagesize"]
            print(f"\n  搜索总结果: {total} 条，共 {total_pages} 页（每页约 {pagesize} 条）")
            if pages > total_pages:
                pages = total_pages
                print(f"  实际只有 {total_pages} 页，调整爬取页数")

        print_videos(videos, start_index=total_count)
        append_to_csv(csv_path, videos, start_index=total_count)
        total_count += len(videos)
        print(f"\n  ✓ 第 {p} 页已追加写入 CSV（累计 {total_count} 条）")

        if p < pages:
            sleep(2)

    print(f'\n{"=" * 70}')
    print(f'  完成! 关键词"{keyword}"共写入 {total_count} 条')
    print(f"  文件: {csv_path}")
    print(f'{"=" * 70}')


if __name__ == "__main__":
    keyword = "Android教程"
    pages_input = 20
    pages = int(pages_input) if pages_input else 1
    search_bilibili(keyword, pages)
