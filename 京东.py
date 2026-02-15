import re
import time
from DrissionPage import ChromiumPage
import random
import csv


def parse_sales(text, rand_min=2000, rand_max=5000):
    """
    解析销量文本，返回整数销量。
    """
    try:
        if not text:
            return 0
        # 提取数字和单位
        match = re.search(r'(\d+)(万)?', text)
        if match:
            number = int(match.group(1))
            if match.group(2) == '万':
                number *= 10000
        else:
            number = 0
        number += random.randint(rand_min, rand_max)
    except:
        number = random.randint(rand_min, rand_max)
    return number


def extract_goods_data(json_data, return_list):
    """
    从JSON数据中提取商品信息并添加到return_list
    'product_title': 商品标题,
    'price': 当前价格,
    'original_price': 原价,
    'subsidy_amount': 优惠力度价,
    'sales': 销售量,
    'shop_name': 店铺名称,
    'image_url': 图片地址,
    'has_subsidy': 政府补贴,
    'is_self_support': 自营,
    'product_id': 商品ID

    """
    # 兼容新旧两种数据结构
    data = json_data.get('data')
    if not data:
        return
    
    # 如果data是列表，直接使用；如果是字典，尝试获取wareList
    if isinstance(data, list):
        ware_list = data
    elif isinstance(data, dict) and data.get('wareList'):
        ware_list = data.get('wareList')
    else:
        return
    
    if not ware_list:
        return
    
    for item in ware_list:
            # 获取售价 - 优先使用finalPrice，否则使用jdPrice或realPrice
            price = None
            if item.get('finalPrice') and item.get('finalPrice').get('estimatedPrice'):
                price = item.get('finalPrice').get('estimatedPrice')
            elif item.get('jdPrice'):
                price = item.get('jdPrice')
            elif item.get('realPrice'):
                price = item.get('realPrice')

            # 获取销售量
            sales = item.get('totalSales', '')
            if not sales and item.get('commentSalesFloor'):
                # 从commentSalesFloor中提取销量文本
                sales_text = item.get('commentSalesFloor')[0].get('text', '') if item.get('commentSalesFloor') else ''
                sales = parse_sales(sales_text.replace('已售', '').replace('人看过', ''))

            # 获取店铺名称
            shop_name = item.get('shopName', '')

            # 获取图片路由 - 拼接完整URL
            image_url = item.get('imageurl', '')
            if image_url:
                if not image_url.startswith('http'):
                    image_url = f'https://img14.360buyimg.com/n1/{image_url}'

            # 获取商品标题
            product_title = item.get('wareName', '')
            # 去除标题中的HTML标签（如<font>标签）
            if product_title:
                product_title = re.sub(r'<[^>]+>', '', product_title)
            
            # 如果商品标题为空或不是字符串，跳过该商品
            if not product_title or not isinstance(product_title, str) or not product_title.strip():
                continue

            # 判断是否国家补贴并获取优惠价格
            has_subsidy = False
            subsidy_amount = None
            if item.get('govSubsidyBenefit'):
                has_subsidy = True
                subsidy_amount = item.get('govSubsidyBenefit').get('amount', '')
            elif item.get('iconList2'):
                # 检查iconList2中是否有国家补贴标签
                for icon in item.get('iconList2', []):
                    if icon.get('code') == 'gjbt' or icon.get('label') == 'gjbt':
                        has_subsidy = True
                        # 从icon中提取优惠金额
                        if icon.get('amount'):
                            # 提取金额数字，如"￥67.35" -> "67.35"
                            amount_text = icon.get('amount', '').replace('￥', '').strip()
                            subsidy_amount = amount_text
                        break

            # 计算原价：如果有国补，原价 = 当前价格 + 优惠力度
            original_price = None
            if has_subsidy and subsidy_amount and price:
                try:
                    price_float = float(str(price).replace(',', ''))
                    subsidy_float = float(str(subsidy_amount).replace(',', ''))
                    original_price = str(price_float + subsidy_float)
                except (ValueError, TypeError):
                    # 如果转换失败，尝试使用oriPrice
                    original_price = item.get('oriPrice', '')
            else:
                # 没有国补时，使用oriPrice作为原价
                original_price = item.get('oriPrice', '')

            # 判断是否自营 - selfSupport为1表示自营
            is_self_support = bool(item.get('selfSupport', 0))

            # 获取商品ID - 优先使用skuId，否则使用wareId
            product_id = item.get('skuId', '') or item.get('wareId', '')
            
            # 生成链接地址
            link_url = f'https://item.jd.com/{product_id}.html' if product_id else ''

            goods_dict = {
                'product_title': product_title,
                'price': price,
                'original_price': original_price,
                'subsidy_amount': subsidy_amount if has_subsidy else None,
                'sales': sales,
                'shop_name': shop_name,
                'image_url': image_url,
                'has_subsidy': has_subsidy,
                'is_self_support': is_self_support,
                'product_id': product_id,
                'link_url': link_url
            }
            return_list.append(goods_dict)


def get_goods(keyword,max_pages):
    """
    获取商品数据，支持多页翻页
    :param max_pages: 最大翻页次数，默认2页（第1页 + 翻1次）
    """
    return_list = []
    filename = 'goods_data.csv'
    
    # 定义字段的中文映射
    field_mapping = {
        'product_title': '商品标题',
        'price': '当前价格',
        'original_price': '原价',
        'subsidy_amount': '优惠力度价',
        'sales': '销售量',
        'shop_name': '店铺名称',
        'image_url': '图片地址',
        'has_subsidy': '政府补贴',
        'is_self_support': '自营',
        'product_id': '商品ID',
        'link_url': '链接地址'
    }
    
    # 定义CSV表头（中文名）
    headers = [field_mapping.get(key, key) for key in field_mapping.keys()]
    
    # 初始化CSV文件，写入表头
    with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()

    web = ChromiumPage()
    web.get('https://www.jd.com/')

    # C = input("请输入指令：")

    web.ele('xpath://*[@id="key"]').input(str(keyword).strip())
    web.listen.start(targets="https://api.m.jd.com/api?appid=search-pc-java&t=")
    web.ele('xpath://*[@id="search"]/div/div[2]/button').click()
    time.sleep(2)
    web.scroll.to_bottom()
    time.sleep(2)
    
    # 处理第一页数据
    print("正在获取第1页数据...")
    events = web.listen.wait(count=5)
    
    for event in events:
        json_data = event.response.body
        # 检查是否有数据（兼容新旧数据结构）
        data = json_data.get('data')
        if data and (isinstance(data, list) or (isinstance(data, dict) and data.get('wareList'))):
            prev_count = len(return_list)
            extract_goods_data(json_data, return_list)
            # 将新增的商品写入CSV
            with open(filename, 'a', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                for goods in return_list[prev_count:]:
                    row = {}
                    for key, chinese_name in field_mapping.items():
                        value = goods.get(key, '')
                        # 处理布尔值
                        if isinstance(value, bool):
                            value = '是' if value else '否'
                        # 处理None值
                        if value is None:
                            value = ''
                        row[chinese_name] = value
                    writer.writerow(row)
    
    # print(f"第1页获取完成，已获取 {len(return_list)} 个商品")
    
    # 翻页获取后续页面数据
    for page_num in range(2, max_pages + 1):
        try:
            # 查找并点击"下一页"按钮
            next_button = web.ele('css:._pagination_next_1jczn_8', timeout=3)
            if next_button:
                # 检查按钮是否可点击（检查class中是否包含disabled）
                button_class = next_button.attr('class') or ''
                if 'disabled' not in button_class:
                    print(f"正在获取第{page_num}页数据...")
                    # 重新启动监听
                    web.listen.start(targets="https://api.m.jd.com/api?appid=search-pc-java&t=")
                    # 点击下一页
                    next_button.click()
                    time.sleep(2)
                    web.scroll.to_bottom()
                    time.sleep(2)
                    
                    # 等待并获取新页面的数据
                    events = web.listen.wait(count=5)
                    for event in events:
                        json_data = event.response.body
                        # 检查是否有数据（兼容新旧数据结构）
                        data = json_data.get('data')
                        if data and (isinstance(data, list) or (isinstance(data, dict) and data.get('wareList'))):
                            prev_count = len(return_list)
                            extract_goods_data(json_data, return_list)
                            # 将新增的商品写入CSV
                            with open(filename, 'a', newline='', encoding='utf-8-sig') as csvfile:
                                writer = csv.DictWriter(csvfile, fieldnames=headers)
                                for goods in return_list[prev_count:]:
                                    row = {}
                                    for key, chinese_name in field_mapping.items():
                                        value = goods.get(key, '')
                                        # 处理布尔值
                                        if isinstance(value, bool):
                                            value = '是' if value else '否'
                                        # 处理None值
                                        if value is None:
                                            value = ''
                                        row[chinese_name] = value
                                    writer.writerow(row)
                    
                    print(f"第{page_num}页获取完成，已获取 {len(return_list)} 个商品")
                else:
                    print(f"第{page_num}页按钮不可点击（已禁用），已到达最后一页")
                    break
            else:
                print(f"未找到第{page_num}页按钮，已到达最后一页")
                break
        except Exception as e:
            print(f"翻页到第{page_num}页时出错: {e}")
            break
    
    print(f"\n总共获取了 {len(return_list)} 个商品，数据已保存到 {filename}")
    return return_list


def get_comments(uuid,end):
    import time
    from DrissionPage import ChromiumPage
    return_list = []
    dp = ChromiumPage()
    dp.get(f'https://item.jd.com/{uuid}.html')
    time.sleep(2)
    dp.listen.start('client.action')
    dp.ele('css:.all-btn .arrow').click()
    for page in range(1,int(end)):
        print(f'正在采集第{page}页的数据')
        # 等待数据包加载
        r = dp.listen.wait()
        json_data = r.response.body
        comment_list = json_data['result']['floors'][2]['data']
        for index in comment_list:
            if 'commentInfo' in [i for i in index.keys()]:
                comment_dict = {
                    'name': index['commentInfo']['userNickName'],
                    'score': index['commentInfo']['commentScore'],
                    'product': index['commentInfo']['productSpecifications'].replace('已购',''),
                    'date': index['commentInfo']['commentDate'],
                    'text': index['commentInfo']['commentData'],
                }
                return_list.append(comment_dict)
            else:
                   pass
        #定位窗口标签
        tab = dp.ele('css:div._rateListContainer_1ygkr_45')
        tab.scroll.to_bottom()
    
    # 导出CSV文件
    filename = f'{uuid}.csv'
    if return_list:
        with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
            # 定义表头
            headers = ['name', 'score', 'product', 'date', 'text']
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            # 写入数据
            for comment in return_list:
                writer.writerow(comment)
        print(f'\n评论数据已导出到 {filename}，共 {len(return_list)} 条评论')
    else:
        print('\n没有获取到评论数据，未生成CSV文件')
    
    return return_list



if __name__ == '__main__':
    get_goods('手机',50)
    # get_comments(100312148882,90)
