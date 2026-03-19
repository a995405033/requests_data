"""
B站排行榜数据请求脚本
提取有效数据用于数据分析，并以中文说明各字段含义
支持 WBI 签名，优先使用 curl_cffi 模拟浏览器绕过 -352 风控
"""

import csv
import hashlib
import time
import urllib.parse
from datetime import datetime




SESSDATA = "buvid3=07FC48EE-66CB-7F3A-E237-3225EB57A65C83322infoc; b_nut=1747634783; _uuid=3482FB5B-C49A-D6FE-17AE-10101C72F1076C483854infoc; enable_web_push=DISABLE; enable_feed_channel=ENABLE; DedeUserID=83848752; DedeUserID__ckMd5=1bc9d990a7ac3f28; rpdid=|(u~JYRJkJ|l0J'u~R~)mRRku; LIVE_BUVID=AUTO5217484121713845; header_theme_version=OPEN; theme-tip-show=SHOWED; theme-avatar-tip-show=SHOWED; fingerprint=f4f045cb2c1a07fc96b9f044c0295975; buvid_fp_plain=undefined; buvid_fp=f4f045cb2c1a07fc96b9f044c0295975; buvid4=3BBB54E5-0D4D-7E39-3693-1365987A1DF484053-025051914-Z7QQAAGY2D/IhP8mx7Abkg%3D%3D; CURRENT_QUALITY=120; hit-dyn-v2=1; home_feed_column=5; PVID=4; bsource=search_google; bp_t_offset_83848752=1168823049789636608; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NzI3NjAzNTgsImlhdCI6MTc3MjUwMTA5OCwicGx0IjotMX0.jVEfVfzAZbE3TTSrkZex44_oAToXU6fFs3a5q553mQc; bili_ticket_expires=1772760298; SESSDATA=bb92172e%2C1788053158%2C71c78%2A32CjCJPgHVNAIXYS4sxcvnLGploVQ-84E1uAvRJvYAPupFeh7tgYJGU8Q1f3APlLo0oFASVndrYUN2QlN0cml3OTJWTnhSdXhvWGtmelh3dmhYQldNNmY5Vm9xQXlBT0F0M0pkRnhuTUdJS2pHMnJBU0JzOWJzRTZaQ19QMVJ5YUE1NllfdDRVRHl3IIEC; bili_jct=0603501bb69b4f6554771b63d737c830; sid=5p9smygo; browser_resolution=2111-1015; CURRENT_FNVAL=2000; b_lsid=071ED5C7_19CB1627B09"  # 必填，登录会话
bili_jct = ""

# ========== 填完后保存此文件即可 ==========
# 从配置文件读取 Cookie（编辑 bilibili_config.py 填入你的 SESSDATA 和 bili_jct）
try:
    from bilibili_config import SESSDATA, bili_jct
    COOKIES = {k: v for k, v in [("SESSDATA", SESSDATA), ("bili_jct", bili_jct)] if v}
except ImportError:
    COOKIES = {}

# 优先使用 curl_cffi（模拟浏览器 TLS 指纹，可有效绕过 -352）
try:
    from curl_cffi import requests as http_client
    USE_CURL_CFFI = True
except ImportError:
    import requests as http_client
    USE_CURL_CFFI = False

# WBI 签名用的字符重排映射表（B站固定）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}


# 轮换使用的浏览器指纹，提高成功率
IMPersonate_OPTIONS = ("chrome110", "chrome116", "chrome124", "safari15_5")


def _get(url, impersonate_index=0, **kwargs):
    """统一请求入口，curl_cffi 时使用 impersonate 模拟浏览器"""
    if COOKIES:
        kwargs.setdefault("cookies", COOKIES)
    if USE_CURL_CFFI:
        imp = IMPersonate_OPTIONS[impersonate_index % len(IMPersonate_OPTIONS)]
        kwargs.setdefault("impersonate", imp)
        return http_client.get(url, **kwargs)
    return http_client.get(url, **kwargs)


def get_wbi_keys(impersonate_index=0):
    """从 nav 接口获取 WBI 签名所需的 img_key 和 sub_key"""
    resp = _get("https://api.bilibili.com/x/web-interface/nav", impersonate_index=impersonate_index, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    wbi_img = data.get("data", {}).get("wbi_img", {})
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0] if img_url else ""
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0] if sub_url else ""
    return img_key, sub_key


def get_mixin_key(orig: str) -> str:
    """按映射表重排密钥，取前32位"""
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB if i < len(orig))[:32]


def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """生成 WBI 签名参数 w_rid 和 wts"""
    mixin_key = get_mixin_key(img_key + sub_key)
    params["wts"] = round(time.time())
    params = dict(sorted(params.items()))
    params = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params


# 分区配置：标签名 -> rid
RANKING_CATEGORIES = {
    "影视": 1001,
    "游戏": 1008,
    "美食": 1020,
    "知识": 1010,
    "娱乐": 1002,
}


def fetch_bilibili_ranking(rid: int, impersonate_index=0):
    """请求 B站排行榜 API 并返回 JSON 数据（自动生成 WBI 签名）"""
    img_key, sub_key = get_wbi_keys(impersonate_index)
    base_params = {
        "rid": rid,
        "type": "all",
        "web_location": "333.934",
    }
    params = enc_wbi(base_params.copy(), img_key, sub_key)

    response = _get(
        "https://api.bilibili.com/x/web-interface/ranking/v2",
        impersonate_index=impersonate_index,
        params=params,
        headers=HEADERS,
    )
    response.raise_for_status()
    return response.json()


def extract_video_data(item):
    """
    从原始数据中提取有效字段，便于数据分析
    返回结构化的字典
    """
    stat = item.get("stat", {})
    owner = item.get("owner", {})
    pubdate = item.get("pubdate", 0)

    return {
        "视频ID": item.get("aid"),
        "BV号": item.get("bvid"),
        "标题": item.get("title"),
        "简介": item.get("desc", "")[:100],  # 截取前100字便于展示
        "UP主ID": owner.get("mid"),
        "UP主昵称": owner.get("name"),
        "分区": item.get("tname"),
        "二级分区": item.get("tnamev2"),
        "发布时间": datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M:%S") if pubdate else None,
        "发布时间戳": pubdate,
        "视频时长秒": item.get("duration"),
        "播放量": stat.get("view", 0),
        "弹幕数": stat.get("danmaku", 0),
        "评论数": stat.get("reply", 0),
        "点赞数": stat.get("like", 0),
        "收藏数": stat.get("favorite", 0),
        "投币数": stat.get("coin", 0),
        "分享数": stat.get("share", 0),
        "发布地区": item.get("pub_location"),
        "封面链接": item.get("pic"),
        "视频链接": item.get("short_link_v2"),
    }


def print_video_item(data, index):
    """用中文打印单条视频的有效数据及字段说明"""
    print(f"\n{'='*50}")
    print(f"【第 {index + 1} 条视频】")
    print(f"{'='*50}")

    # 字段说明对照表
    field_desc = {
        "视频ID": "视频唯一标识（av号）",
        "BV号": "视频的BV号，用于分享链接",
        "标题": "视频标题",
        "简介": "视频描述/简介（前100字）",
        "UP主ID": "UP主用户ID",
        "UP主昵称": "UP主昵称",
        "分区": "视频所属分区（如：绘画、游戏）",
        "二级分区": "更细分的分类（如：AI影视）",
        "发布时间": "视频发布时间（可读格式）",
        "发布时间戳": "发布时间（Unix时间戳，用于计算）",
        "视频时长秒": "视频时长，单位：秒",
        "播放量": "总播放次数",
        "弹幕数": "弹幕数量",
        "评论数": "评论数量",
        "点赞数": "点赞数量",
        "收藏数": "收藏数量",
        "投币数": "投币数量",
        "分享数": "分享次数",
        "发布地区": "UP主发布时的地理位置",
        "封面链接": "视频封面图片URL",
        "视频链接": "视频短链接",
    }

    for key, value in data.items():
        desc = field_desc.get(key, "")
        if desc:
            print(f"  {key}（{desc}）: {value}")
        else:
            print(f"  {key}: {value}")


def save_to_csv(data_list: list, filename: str):
    """将数据列表保存为 CSV 文件"""
    if not data_list:
        return
    fieldnames = list(data_list[0].keys())
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data_list)
    print(f"  已保存到 {filename}，共 {len(data_list)} 条")


def crawl_all_categories():
    """爬取所有分区排行榜并保存到对应 CSV"""
    if COOKIES:
        print("已加载 Cookie（bilibili_config.py）\n")
    if USE_CURL_CFFI:
        print("使用 curl_cffi 模拟浏览器\n")
    if not COOKIES and not USE_CURL_CFFI:
        print("提示：在 bilibili_config.py 填 Cookie 或执行 pip install curl_cffi 可提高成功率\n")

    for label, rid in RANKING_CATEGORIES.items():
        print(f"\n正在爬取【{label}】分区 (rid={rid})...")
        success = False
        for attempt in range(4):
            try:
                # 每次重试换一个浏览器指纹
                raw_data = fetch_bilibili_ranking(rid, impersonate_index=attempt)

                if raw_data.get("code") != 0:
                    if attempt < 3:
                        delay = 5 * (attempt + 1)
                        print(f"  请求失败 (code={raw_data.get('code')})，{delay} 秒后换指纹重试...")
                        time.sleep(delay)
                        continue
                    print(f"  请求失败: code={raw_data.get('code')}, message={raw_data.get('message')}")
                    break

                video_list = raw_data.get("data", {}).get("list", [])
                if not video_list:
                    print(f"  未获取到数据")
                    break

                data_list = [extract_video_data(item) for item in video_list]
                csv_name = f"{label}.csv"
                save_to_csv(data_list, csv_name)
                success = True
                break

            except Exception as e:
                if attempt < 3:
                    delay = 5 * (attempt + 1)
                    print(f"  爬取失败: {e}，{delay} 秒后重试...")
                    time.sleep(delay)
                else:
                    print(f"  爬取失败: {e}")
                break

        time.sleep(3)  # 间隔 3 秒，避免触发风控

    print("\n全部完成！")


def main():
    """单分区模式：仅爬取影视分区并打印（兼容旧用法）"""
    print("正在请求 B站排行榜 API（影视分区）...")
    raw_data = fetch_bilibili_ranking(RANKING_CATEGORIES["影视"])

    if raw_data.get("code") != 0:
        code = raw_data.get("code")
        msg = raw_data.get("message", "未知错误")
        print(f"请求失败: code={code}, message={msg}")
        return

    video_list = raw_data.get("data", {}).get("list", [])
    if not video_list:
        print("未获取到数据")
        return

    data_list = [extract_video_data(item) for item in video_list]

    print(f"\n共获取到 {len(data_list)} 条视频，已提取有效数据\n")
    print("【字段说明】")
    print("  - 以下为数据分析常用字段，已过滤无关项")
    print("  - 可直接用 pandas.DataFrame(data_list) 进行后续分析\n")

    for i, data in enumerate(data_list):
        print_video_item(data, i)

    return data_list


if __name__ == "__main__":
    crawl_all_categories()
