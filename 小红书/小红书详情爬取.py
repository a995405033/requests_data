import time
from DrissionPage import ChromiumPage
from DrissionPage.common import Actions


def scroll_down(page, times=3, delay=2):
    """向下滚动若干次以加载动态数据"""
    for i in range(times):
        page.scroll.to_bottom()
        time.sleep(delay)


def find_want(data, target_key):
    # 处理数据为字典的递归遍历
    if isinstance(data, dict):
        for key, val in data.items():
            if key == target_key:
                return val
            # 递归遍历子元素
            ret = find_want(val, target_key)
            if ret:
                return ret
    elif isinstance(data, list):
        for i in data:
            ret = find_want(i, target_key)
            if ret:
                return ret
    else:
        return None


if __name__ == '__main__':
    page = ChromiumPage()

    # 监听数据接口 -- 尽量写在最前面
    page.listen.start('web/v1/feed')  # 形如这种格式的会被抓取
    page.get(f'https://www.xiaohongshu.com/search_result?keyword=汕头&source=web_profile_page')
    page.wait.load_start()
    s = set()
    print("开始派遣")
    # 爬取二十条数据
    data_count = 0
    max_count = 3
    error_count = 0
    scroll_interval = 5  # 每采集五条滚动一次
    while data_count < max_count:
        try:
            cards = page.eles('xpath://*[@id="global"]/div[2]/div[2]/div/div/div[3]/div[1]/section')
            for card in cards:
                if data_count >= max_count:
                    break
                # 去重
                index = card.attr('data-index')
                if index in s:
                    continue
                s.add(index)

                print(f'正在爬取第{data_count + 1}条数据...')

                # 点击卡片并获取数据
                card.ele('xpath:./div/a[2]/img').click(by_js=True)  # 用js点击，如用默认的False，则是模拟点击，可能会被因为图层遮蔽无法点到
                res = page.listen.wait(count=1, timeout=3, fit_count=True)  # 匹配数量/超时等待时间/是否严格匹配
                data = res.response.body
                # 数据提取
                nickname = find_want(data, 'nickname')
                title = find_want(data, 'title')
                desc = find_want(data, 'desc')
                comment_count = find_want(data, 'comment_count')
                liked_count = find_want(data, 'liked_count')
                collected_count = find_want(data, 'collected_count')  # 收藏数
                share_count = find_want(data, 'share_count')  # 分享数
                view_count = find_want(data, 'view_count')  # 浏览量
                user_id = find_want(data, 'user_id')  # 用户ID
                note_id = find_want(data, 'note_id') or find_want(data, 'id')  # 笔记ID
                time = find_want(data, 'time') or find_want(data, 'create_time') or find_want(data, 'timestamp')  # 发布时间
                location = find_want(data, 'location') or find_want(data, 'poi_name')  # 位置信息
                type_ = find_want(data, 'type') or find_want(data, 'note_type')  # 笔记类型

                # 提取图片列表
                images = find_want(data, 'images') or find_want(data, 'image_list') or find_want(data, 'cover')
                image_urls = []
                if images:
                    if isinstance(images, list):
                        for img in images:
                            if isinstance(img, dict):
                                # 尝试多种可能的图片URL字段
                                url = img.get('url') or img.get('url_prefix') or img.get('info_list') or img.get(
                                    'original')
                                if url:
                                    if isinstance(url, list) and len(url) > 0:
                                        url = url[0].get('url') if isinstance(url[0], dict) else url[0]
                                    image_urls.append(str(url))
                            elif isinstance(img, str):
                                image_urls.append(img)
                    elif isinstance(images, str):
                        image_urls.append(images)
                    elif isinstance(images, dict):
                        url = images.get('url') or images.get('url_prefix')
                        if url:
                            image_urls.append(str(url))

                # 提取标签
                tags = find_want(data, 'tags') or find_want(data, 'tag_list')
                tag_list = []
                if tags:
                    if isinstance(tags, list):
                        for tag in tags:
                            if isinstance(tag, dict):
                                tag_name = tag.get('name') or tag.get('tag') or tag.get('tag_name')
                                if tag_name:
                                    tag_list.append(str(tag_name))
                            elif isinstance(tag, str):
                                tag_list.append(tag)
                    elif isinstance(tags, str):
                        tag_list.append(tags)

                # 基于recorder将采集数据写入excel
                map_ = {
                    '博主昵称': nickname,
                    '用户ID': user_id,
                    '标题': title,
                    '详情': desc,
                    '笔记ID': note_id,
                    '评论数': comment_count,
                    '点赞数': liked_count,
                    '收藏数': collected_count,
                    '分享数': share_count,
                    '浏览量': view_count,
                    '发布时间': time,
                    '位置': location,
                    '笔记类型': type_,
                    '详情图片': ', '.join(image_urls) if image_urls else None,  # 图片URL用逗号分隔
                    '图片数量': len(image_urls) if image_urls else 0,
                    '标签': ', '.join(tag_list) if tag_list else None,  # 标签用逗号分隔
                }
                print("map_", map_)

                # 关闭卡片+等待
                page.ele('xpath:/html/body/div[5]/div[2]/div').click()
                page.wait.load_start()
                # time.sleep(3)
                data_count += 1

                # 每采集一定数量滚动一次
                if data_count % scroll_interval == 0:
                    page.scroll.down(1000)
                    page.wait.load_start()
                    # break
        except Exception as e:
            print("error", e)
            error_count += 1
            if error_count > max_count:
                print(f'错误超过{max_count}次，停止采集!')
                break
            continue
    if data_count >= max_count:
        print(f'已爬取{data_count}条数据项打印完成!')
    else:
        print(f'共采集到{data_count}条数据')
