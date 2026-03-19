"""
B站关键词搜索 - 使用 DrissionPage 按关键词+页数爬取搜索结果
从页面 window.__pinia 提取数据，支持翻页
"""
from DrissionPage import ChromiumPage
from time import sleep
from datetime import datetime
import json
import re
import csv
import os


def clean_html(text):
    """去掉B站搜索结果中的 <em> 高亮标签"""
    if not text:
        return ''
    return re.sub(r'<[^>]+>', '', text)


def format_number(n):
    if not isinstance(n, (int, float)):
        return str(n)
    if n >= 100000000:
        return f'{n / 100000000:.1f}亿'
    if n >= 10000:
        return f'{n / 10000:.1f}万'
    return str(n)


JS_EXTRACT = """
try {
    const pinia = window.__pinia;
    const resp = pinia.searchResponse.searchAllResponse;
    let videos = [];
    for (const group of resp.result) {
        if (group.data) {
            for (const item of group.data) {
                if (item.type === 'video') {
                    videos.push(item);
                }
            }
        }
    }
    return JSON.stringify({
        numResults: resp.numResults,
        page: resp.page,
        pagesize: resp.pagesize,
        numPages: resp.numPages,
        videos: videos
    });
} catch(e) {
    return JSON.stringify({error: e.message});
}
"""


def fetch_page(page, keyword, page_num):
    """
    爬取B站搜索结果的单页数据

    参数:
        page: ChromiumPage 浏览器实例
        keyword: 搜索关键词
        page_num: 页码（从1开始）

    返回:
        dict: {numResults, page, pagesize, numPages, videos: [...]}
        None: 失败时返回
    """
    offset = (page_num - 1) * 30
    search_url = f'https://search.bilibili.com/all?keyword={keyword}&page={page_num}&o={offset}'
    print(f'\n  正在加载第 {page_num} 页: {search_url}')
    page.get(search_url)
    sleep(4)

    result = page.run_js(JS_EXTRACT)
    data = json.loads(result)

    if 'error' in data:
        print(f'  提取失败: {data["error"]}')
        return None

    print(f'  本页获取 {len(data["videos"])} 个视频')
    return data


def print_videos(videos, start_index=0):
    """打印视频列表"""
    for i, v in enumerate(videos):
        title = clean_html(v.get('title', ''))
        desc = clean_html(v.get('description', ''))
        pic = v.get('pic', '')
        if pic and pic.startswith('//'):
            pic = 'https:' + pic

        pubdate = v.get('pubdate', 0)
        pub_time = datetime.fromtimestamp(pubdate).strftime('%Y-%m-%d %H:%M') if pubdate else v.get('pubstr', '-')

        idx = start_index + i + 1
        print(f'\n  ── 第 {idx} 条 ──')
        print(f'  标题:     {title}')
        print(f'  BV号:     {v.get("bvid", "-")}')
        print(f'  AV号:     {v.get("aid", "-")}')
        print(f'  UP主:     {v.get("author", "-")} (UID: {v.get("mid", "-")})')
        print(f'  分区:     {v.get("typename", "-")}')
        print(f'  时长:     {v.get("duration", "-")}')
        print(f'  发布时间: {pub_time}')
        print(f'  播放量:   {format_number(v.get("play", 0))}')
        print(f'  点赞:     {format_number(v.get("like", 0))}')
        print(f'  收藏:     {format_number(v.get("favorites", 0))}')
        print(f'  弹幕:     {format_number(v.get("danmaku", 0))}')
        print(f'  评论:     {format_number(v.get("review", 0))}')
        print(f'  标签:     {v.get("tag", "-")}')
        print(f'  简介:     {desc[:80] if desc else "-"}')
        print(f'  封面:     {pic}')


CSV_HEADERS = [
    '序号', '标题', 'BV号', 'AV号', 'UP主', 'UID',
    '分区', '时长', '发布时间', '播放量', '点赞',
    '收藏', '弹幕', '评论', '标签', '简介', '封面'
]


def init_csv(keyword):
    """初始化CSV文件，写入表头，返回文件路径"""
    filename = f'B站搜索_{keyword}.csv'
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)

    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f).writerow(CSV_HEADERS)

    print(f'  CSV文件已创建: {filepath}')
    return filepath


def append_to_csv(filepath, videos, start_index):
    """将一页视频数据追加写入CSV"""
    with open(filepath, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        for i, v in enumerate(videos):
            title = clean_html(v.get('title', ''))
            desc = clean_html(v.get('description', ''))
            pic = v.get('pic', '')
            if pic and pic.startswith('//'):
                pic = 'https:' + pic

            pubdate = v.get('pubdate', 0)
            pub_time = datetime.fromtimestamp(pubdate).strftime('%Y-%m-%d %H:%M') if pubdate else v.get('pubstr', '-')

            writer.writerow([
                start_index + i + 1,
                title,
                v.get('bvid', ''),
                v.get('aid', ''),
                v.get('author', ''),
                v.get('mid', ''),
                v.get('typename', ''),
                v.get('duration', ''),
                pub_time,
                v.get('play', 0),
                v.get('like', 0),
                v.get('favorites', 0),
                v.get('danmaku', 0),
                v.get('review', 0),
                v.get('tag', ''),
                desc,
                pic
            ])


def search_bilibili(keyword, pages=1):
    """
    B站关键词搜索主函数

    参数:
        keyword: 搜索关键词
        pages: 要爬取的页数（默认1页）
    """
    print(f'{"=" * 70}')
    print(f'  B站搜索: "{keyword}"  |  计划爬取 {pages} 页')
    print(f'{"=" * 70}')

    browser = ChromiumPage()
    csv_path = init_csv(keyword)
    total_count = 0

    for p in range(1, pages + 1):
        data = fetch_page(browser, keyword, p)
        if not data:
            print(f'  第 {p} 页获取失败，停止')
            break

        videos = data['videos']
        if not videos:
            print(f'  第 {p} 页没有数据了，停止翻页')
            break

        if p == 1:
            total = data['numResults']
            total_pages = data['numPages']
            pagesize = data['pagesize']
            print(f'\n  搜索总结果: {total} 条，共 {total_pages} 页（每页约 {pagesize} 条）')
            if pages > total_pages:
                pages = total_pages
                print(f'  实际只有 {total_pages} 页，调整爬取页数')

        print_videos(videos, start_index=total_count)
        append_to_csv(csv_path, videos, start_index=total_count)
        total_count += len(videos)
        print(f'\n  ✓ 第 {p} 页已追加写入CSV（累计 {total_count} 条）')

        if p < pages:
            sleep(2)

    print(f'\n{"=" * 70}')
    print(f'  完成! 关键词"{keyword}"共爬取 {total_count} 条视频')
    print(f'  文件: {csv_path}')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    keyword = "非遗"
    pages_input = 50
    pages = int(pages_input) if pages_input else 1

    search_bilibili(keyword, pages)
