import requests
from bs4 import BeautifulSoup
import time
import csv
import os

headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-encoding': 'gzip, deflate, br, zstd',
    'accept-language': 'zh-CN,zh;q=0.9',
    'connection': 'keep-alive',
    'cookie':'SECKEY_ABVK=+XWfWBxCkbt9hsZ09PxRx+vaXO8WyzCzhlHMTmJmfnY%3D; BMAP_SECKEY=6wIkoP8ZawhMChGfT_D1Wndf6po47dVzax5nhy_IwLyB7JzJTVsBfaEE8Yc4yjneSoYO3391IuvMhj6YjzXkre-4jL3M15choNmrNcDSff4JOxxWKWhtajmRJY7Yhb2iRS1AhCZYhEW70IaxwCnuOS5xvyRu46L_6qNH_pxcxqtXEGPPy-fzw2ZfwwwfOs3R; lianjia_uuid=7123c6e4-f0ea-4876-b139-25c9aa10b498; lianjia_ssid=4e291952-bd71-4517-887c-717e42a70595; Hm_lvt_46bf127ac9b856df503ec2dbf942b67e=1774592571; HMACCOUNT=F779C95812CD1C19; _jzqa=1.655227246013863000.1774592571.1774592571.1774592571.1; _jzqc=1; _jzqx=1.1774592571.1774592571.1.jzqsr=google%2Ecom|jzqct=/.-; _jzqckmp=1; sajssdk_2015_cross_new_user=1; _ga=GA1.2.1969865991.1774592575; _gid=GA1.2.160685206.1774592575; _ga_WLZSQZX7DE=GS2.2.s1774592575$o1$g1$t1774592580$j55$l0$h0; _ga_TJZVFLS7KV=GS2.2.s1774592575$o1$g1$t1774592580$j55$l0$h0; select_city=510100; _qzjc=1; _ga_1DRRK8JCYW=GS2.2.s1774592619$o1$g1$t1774592622$j57$l0$h0; crosSdkDT2019DeviceId=-q7to2g-6q5dpm-lygz2jnslrt6ltu-moj2rvl7d; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219d2df5b88e2091-0a6aabdc6301dc8-16525636-2073600-19d2df5b88f2fd0%22%2C%22%24device_id%22%3A%2219d2df5b88e2091-0a6aabdc6301dc8-16525636-2073600-19d2df5b88f2fd0%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_referrer%22%3A%22%22%2C%22%24latest_referrer_host%22%3A%22%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%7D%7D; _ga_XLL3Z3LPTW=GS2.2.s1774592587$o1$g1$t1774593762$j60$l0$h0; _ga_NKBFZ7NGRV=GS2.2.s1774592587$o1$g1$t1774593762$j60$l0$h0; hip=C-Sdl797ndJ12-wGsILgC8msFXK-6wjl21GrqR3WMVC_qoT7AWh7u-j0B_1TEYgV-EXAwwTi8A7qY8wV6DzJWSelRryLbQcDnzrc16Zj2HY_PkCmzMotQGpo0AqGCZE8Wm5j3NaYpEafJI0qxbXI6LKaLlYM3fo5Q3hMOhRWcPUFpysEWQrsICvPGcyUNtdAOuGCmq1sGe0JXaAoMbz-W0Qm3_RtWtNx_DAkUrm_DXsw2EmMZuroHgK4_RearGeXZlSEwg%3D%3D; _qzja=1.1972030987.1774592583348.1774592583348.1774592583348.1774593751217.1774594307137.0.0.0.17.1; _qzjb=1.1774592583348.17.0.0.0; _qzjto=17.1.0; _jzqb=1.21.10.1774592571.1; Hm_lpvt_46bf127ac9b856df503ec2dbf942b67e=1774594307; srcid=eyJ0Ijoie1wiZGF0YVwiOlwiMDYxZjRiODFlZTk5YjBlYjUzM2I1M2ZmY2RhNGM3ZDRhOWJiYTdlNGM0MzljYWE1MWVmOGZkOTdhZWJiYmQ3ZTcwYzUyY2RlMTJjMGUxYzQ4NzYzOTFmZGFiNmY2M2MzZmE4NmNjMjQzOTA0Njc4YjJlOGMwOTk0NGEzOGIwNmUyYWI1OGU1M2M3MDQ3ZjYyYmU1ZTE0YzJiYjA2NzNiNjdiMTVjYTlkNDEwZWYxZDIzZDliNTE5OTVlZTBmNjZiNmQxOWJlZTE2OTU2YTlkNTc4ZGM4YWZiMDc1NTY1NTA3ZjUwZmJlNjU1Zjk4NmNiNzE0ZjViMDIwZjQzNDZkOFwiLFwia2V5X2lkXCI6XCIxXCIsXCJzaWduXCI6XCIzZTdiOWU2ZFwifSIsInIiOiJodHRwczovL2NkLmxpYW5qaWEuY29tL2Vyc2hvdWZhbmcvcGcyLyIsIm9zIjoid2ViIiwidiI6IjAuMSJ9',
    'host': 'cd.lianjia.com',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'
}

base_url = 'https://cd.lianjia.com/ershoufang/pg{}/'

filename = '成都二手房数据.csv'
fieldnames = ['标题', '小区名称', '所在区域', '户型', '面积', '朝向',
              '装修', '楼层', '建成年份', '建筑类型', '总价(万)', '单价',
              '关注信息', '标签', '房源编号', '链接']

# 读取已有CSV中的标题，用于去重
existing_titles = set()
if os.path.exists(filename):
    with open(filename, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_titles.add(row['标题'])
    print(f'已读取现有数据，共 {len(existing_titles)} 条已存在记录')
else:
    print('未找到已有文件，将新建CSV')

# 若文件不存在则写入表头，否则追加
file_exists = os.path.exists(filename)
csv_file = open(filename, 'a', newline='', encoding='utf-8-sig')
writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
if not file_exists:
    writer.writeheader()

new_count = 0
skip_count = 0

start_page = 2
end_page = 15  # 先爬3页测试，需要更多可以修改

for page in range(start_page, end_page + 1):
    url = base_url.format(page)
    print(f'正在请求第 {page} 页: {url}')

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'

        if response.status_code != 200:
            print(f'  请求失败，状态码: {response.status_code}')
            continue

        soup = BeautifulSoup(response.text, 'html.parser')
        house_list = soup.select('ul.sellListContent > li.clear')

        if not house_list:
            print(f'  第 {page} 页未找到房源数据，可能需要更新cookie')
            continue

        print(f'  找到 {len(house_list)} 条房源')

        for item in house_list:
            title_tag = item.select_one('div.title a')
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            house_code = title_tag.get('data-housecode', '')
            link = title_tag.get('href', '')

            position_tags = item.select('div.positionInfo a')
            community = position_tags[0].get_text(strip=True) if len(position_tags) > 0 else ''
            district = position_tags[1].get_text(strip=True) if len(position_tags) > 1 else ''

            house_info_tag = item.select_one('div.houseInfo')
            house_info = house_info_tag.get_text(strip=True) if house_info_tag else ''

            parts = [p.strip() for p in house_info.split('|')]
            layout = parts[0] if len(parts) > 0 else ''
            area = parts[1] if len(parts) > 1 else ''
            direction = parts[2] if len(parts) > 2 else ''
            decoration = parts[3] if len(parts) > 3 else ''
            floor = parts[4] if len(parts) > 4 else ''
            year = parts[5] if len(parts) > 5 else ''
            building_type = parts[6] if len(parts) > 6 else ''

            follow_tag = item.select_one('div.followInfo')
            follow_info = follow_tag.get_text(strip=True) if follow_tag else ''

            tag_spans = item.select('div.tag span')
            tags = '/'.join([s.get_text(strip=True) for s in tag_spans])

            total_price_tag = item.select_one('div.totalPrice span')
            total_price = total_price_tag.get_text(strip=True) if total_price_tag else ''

            unit_price_tag = item.select_one('div.unitPrice span')
            unit_price = unit_price_tag.get_text(strip=True) if unit_price_tag else ''

            house = {
                '标题': title,
                '小区名称': community,
                '所在区域': district,
                '户型': layout,
                '面积': area,
                '朝向': direction,
                '装修': decoration,
                '楼层': floor,
                '建成年份': year,
                '建筑类型': building_type,
                '总价(万)': total_price,
                '单价': unit_price,
                '关注信息': follow_info,
                '标签': tags,
                '房源编号': house_code,
                '链接': link,
            }

            if title in existing_titles:
                print(f'    [跳过重复] {title}')
                skip_count += 1
            else:
                writer.writerow(house)
                csv_file.flush()
                existing_titles.add(title)
                new_count += 1
                print(f'    [新增] 小区: {community} | 户型: {layout} | 面积: {area} | '
                      f'总价: {total_price}万 | 单价: {unit_price} | 区域: {district}')

    except Exception as e:
        print(f'  第 {page} 页请求异常: {e}')

    time.sleep(2)

csv_file.close()
print(f'\n本次新增 {new_count} 条，跳过重复 {skip_count} 条')
print(f'数据已保存到: {filename}')
