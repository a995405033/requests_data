import csv
import json
import time
import requests
from fake_useragent import UserAgent


def create_session(proxy_url=None):
    """创建带随机UA的请求会话，proxy_url不为None时启用代理"""
    session = requests.Session()
    session.headers.update({'User-Agent': UserAgent().random})
    if proxy_url:
        session.proxies.update({
            'http': proxy_url,
            'https': proxy_url
        })
    return session


def build_request_body(district_id, page_index):
    """拼装请求参数"""
    return {
        "count": 10,
        "districtId": district_id,
        "filter": {"filterItems": ["0"]},
        "head": {
            "cid": "09031115218275213798",
            "ctok": "",
            "cver": "1.0",
            "lang": "01",
            "sid": "8888",
            "syscode": "999",
            "auth": "",
        },
        "index": page_index,
        "returnModuleType": "product",
        "scene": "online",
        "sortType": 1
    }


def parse_attraction(card):
    """从卡片数据中提取景点信息"""
    return {
        "景点名称": card.get("poiName", ""),
        "所属城市": card.get("districtName", ""),
        "所属区域": card.get("zoneName", ""),
        "景区等级": card.get("sightLevelStr", ""),
        "景点分类": card.get("sightCategoryInfo", ""),
        "评论数量": card.get("commentCount", ""),
        "评论评分": card.get("commentScore", ""),
        "热度评分": card.get("heatScore", ""),
        "门票价格": card.get("price", 0),
        "是否免费": "是" if card.get("isFree", False) else "否",
        "标签": "、".join(card.get("tagNameList", [])),
        "封面图片": card.get("coverImageUrl", ""),
        "详情链接": card.get("detailUrl", ""),
    }


def crawl_attractions(city_ids, start_page=1, end_page=5, proxy_url=None):
    """
    爬取携程景点数据
    :param city_ids: 城市ID列表，比如 [1, 2, 4, 5]
    :param start_page: 起始页码
    :param end_page: 结束页码
    :param proxy_url: 代理地址
    :return: 所有景点数据的列表
    """
    api_url = "https://m.ctrip.com/restapi/soa2/18109/json/getAttractionList"
    session = create_session(proxy_url)
    results = []

    for city_id in city_ids:
        for page in range(start_page, end_page + 1):
            time.sleep(1)
            body = build_request_body(city_id, page)
            try:
                resp = session.post(api_url, json=body)
                resp.encoding = resp.apparent_encoding
                resp_json = resp.json()
                attraction_list = resp_json.get("attractionList", [])
            except Exception as e:
                print(f"请求失败 city_id={city_id} page={page}: {e}")
                continue

            for item in attraction_list:
                try:
                    card = item.get("card", {})
                    info = parse_attraction(card)
                    results.append(info)
                    print(f"[{info['所属城市']}] {info['景点名称']} | 热度:{info['热度评分']} | 评分:{info['评论评分']}")
                except Exception:
                    pass

            time.sleep(2)

    return results


def save_to_csv(data, filename="携程景点数据.csv"):
    """把采集到的数据写入CSV文件"""
    if not data:
        print("没有数据可以保存")
        return
    fieldnames = data[0].keys()
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"数据已保存到 {filename}，共 {len(data)} 条")


if __name__ == "__main__":
    # 城市ID参考：https://gist.github.com/chenyueling/c837fe1ef6c7ece53cc1
    city_list = [
        2131
    ]
    data = crawl_attractions(city_list, start_page=1, end_page=150, proxy_url="http://127.0.0.1:7890")
    save_to_csv(data)
    print(f"\n共采集到 {len(data)} 条景点数据")
