from DrissionPage import ChromiumPage
import csv
import os
import time
from datetime import datetime, timedelta

# 获取今天和明天的日期
today = datetime.now()
tomorrow = today + timedelta(days=1)
checkin_date = today.strftime("%Y-%m-%d")
checkout_date = tomorrow.strftime("%Y-%m-%d")

url = (
    "https://hotels.ctrip.com/hotels/list?flexType=1&fixedDate=0&cityId=-1&provinceId=23&countryId=1&cityName=&destName=%E5%B9%BF%E4%B8%9C&searchType=P&checkin=2026-02-06&checkout=2026-02-07&crn=1&listFilters=29~1*29*1~1*2%2C17~1*17*1%2C75~TAG_510*75*510%2C80~2*80*2&curr=CNY&locale=zh-CN&old=1"
)


def crawl_ctrip_hotels(
        target_url: str = url,
        csv_path: str = "./hotel_info.csv",
        max_pages: int = 5,
        scroll_wait: int = 5,
        listen_timeout: int = 20
):
    """
    爬取携程酒店列表数据（监听 fetchHotelList JSON）

    :param target_url: 携程酒店列表页 URL
    :param csv_path: CSV 保存路径
    :param max_pages: 最大滚动页数
    :param scroll_wait: 每次滚动等待秒数
    :param listen_timeout: 监听 JSON 超时时间
    :return: 酒店信息列表（list[dict]）
    """

    # 1. 启动浏览器
    page = ChromiumPage()
    page.get(target_url)

    # 2. 定义CSV表头
    fieldnames = [
        "酒店链接", "酒店名称", "类型", "星级", "城市", "区域", "地址",
        "评分", "评分描述", "评论数", "分项评分",
        "房型名称", "价格", "显示价格", "划线价", "床型", "优惠标签", "图片"
    ]

    # 3. 检查CSV文件是否存在，不存在则写入表头
    file_exists = os.path.exists(csv_path)
    
    print("=" * 80)
    print(f"开始爬取携程民宿数据（最多滚动 {max_pages} 页）")
    print(f"数据将保存到：{csv_path}")
    print("=" * 80)

    page_count = 0
    total_hotels = 0
    empty_retry_count = 0  # 空列表重试计数器
    max_empty_retries = 3  # 最大重试次数

    while page_count < max_pages:
        page_count += 1
        print(f"\n【第 {page_count} 页】开始监听数据...")

        # 4. 开始监听指定接口
        page.listen.start('fetchHotelList')

        # 5. 滚动页面触发加载
        page.scroll.to_bottom()
        time.sleep(scroll_wait)

        # 6. 等待接口响应
        resp = page.listen.wait(timeout=listen_timeout)

        if not resp:
            print(f"  未捕获到新的 JSON 响应，可能已加载完毕")
            break

        json_data = resp.response.body

        # 7. 校验 JSON 结构（最新接口路径：data -> hotelList）
        try:
            hotel_list = json_data['data']['hotelList']
        except (KeyError, TypeError) as e:
            print(f"  数据结构异常：{e}，停止抓取")
            break

        if not hotel_list:
            empty_retry_count += 1
            print(f"  ⚠️  酒店列表为空（第 {empty_retry_count}/{max_empty_retries} 次）")
            
            if empty_retry_count >= max_empty_retries:
                print(f"  已重试 {max_empty_retries} 次，列表仍为空，停止抓取")
                break
            
            print(f"  等待 30 秒后重试...")
            time.sleep(30)
            page_count -= 1  # 不计入页数，重新尝试当前页
            continue

        # 成功获取数据，重置重试计数器
        empty_retry_count = 0
        print(f"  本页获取到 {len(hotel_list)} 条酒店数据，开始解析并保存...")

        # 8. 解析并立即保存每条数据
        with open(csv_path, 'a', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # 如果是新文件，写入表头
            if not file_exists:
                writer.writeheader()
                file_exists = True

            # 解析每条酒店数据
            for idx, item in enumerate(hotel_list, 1):
                try:
                    hotel_info = item.get("hotelInfo", {})
                    room_info_list = item.get("roomInfo", [])

                    # —— 酒店基本信息 ——
                    summary = hotel_info.get("summary", {})
                    name_info = hotel_info.get("nameInfo", {})
                    category = hotel_info.get("hotelCategory", {})
                    position = hotel_info.get("positionInfo", {})
                    comment = hotel_info.get("commentInfo", {})
                    star_info = hotel_info.get("hotelStar", {})
                    images = hotel_info.get("hotelImages", {})

                    # 获取第一张图片
                    multi_imgs = images.get("multiImgs", [])
                    first_img = multi_imgs[0].get("url", "") if multi_imgs else ""

                    # 构建酒店详情链接
                    hotel_id = summary.get("hotelId", "")
                    city_id = position.get("cityId", "")
                    city_en_name = position.get("cityNameEn", "")
                    hotel_link = (
                        f"https://hotels.ctrip.com/hotels/detail/"
                        f"?cityEnName={city_en_name}&cityId={city_id}&hotelId={hotel_id}"
                    ) if hotel_id and city_id else ""

                    # —— 房间/价格信息（取第一个房型） ——
                    room = room_info_list[0] if room_info_list else {}
                    room_summary = room.get("summary", {})
                    price_info = room.get("priceInfo", {})
                    bed_info = room.get("bedInfo", {})

                    # 优惠标签
                    room_tags = room.get("roomTags", {})
                    advantage_tags = room_tags.get("advantageTags", [])
                    advantage_text = "、".join(t.get("tagTitle", "") for t in advantage_tags)

                    # 评分子项
                    sub_scores = comment.get("subScore", [])
                    sub_score_text = " | ".join(
                        f'{s.get("content", "")}:{s.get("number", "")}' for s in sub_scores
                    )

                    info = {
                        "酒店链接": hotel_link,
                        "酒店名称": name_info.get("name", ""),
                        "类型": category.get("categoryName", ""),
                        "星级": star_info.get("star", ""),
                        "城市": position.get("cityName", ""),
                        "区域": "、".join(position.get("zoneNames", [])),
                        "地址": position.get("address", ""),
                        "评分": comment.get("commentScore", ""),
                        "评分描述": comment.get("commentDescription", ""),
                        "评论数": comment.get("commenterNumber", ""),
                        "分项评分": sub_score_text,
                        "房型名称": room_summary.get("saleRoomName", ""),
                        "价格": price_info.get("price", ""),
                        "显示价格": price_info.get("displayPrice", ""),
                        "划线价": price_info.get("deleteDisplayPrice", ""),
                        "床型": "、".join(bed_info.get("contentList", [])),
                        "优惠标签": advantage_text,
                        "图片": first_img,
                    }

                    # 写入CSV
                    writer.writerow(info)
                    total_hotels += 1

                    # 打印到终端
                    print(f"  [{idx}/{len(hotel_list)}] {info['酒店名称']} | {info['显示价格']} | {info['评分']}分 | {info['城市']}")
                    print(f"      链接: {info['酒店链接']}")

                except Exception as e:
                    print(f"  ⚠️  解析第 {idx} 条数据时出错：{e}，跳过")
                    continue

        print(f"  ✅ 第 {page_count} 页完成，累计保存 {total_hotels} 条数据")

    print("\n" + "=" * 80)
    print(f"爬取完成！共爬取 {page_count} 页，保存 {total_hotels} 条酒店数据")
    print(f"数据已保存到：{csv_path}")
    print("=" * 80)

    return total_hotels


if __name__ == "__main__":
    # 用户可以在这里设置滚动页数
    MAX_PAGES = 1500  # 修改这个数字来设置要爬取的页数
    
    crawl_ctrip_hotels(max_pages=MAX_PAGES)
