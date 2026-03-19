""" 爬虫文件 - 已经爬取  无需再爬 """
import os
import random


if __name__ == '__main__':
    import requests
    from fake_useragent import UserAgent
    from lxml import etree

    session = requests.Session()
    session.headers.update({'User-Agent': UserAgent().random})
    for i in range(0, 275, 25):
        page = session.get(url=f"https://movie.douban.com/top250?start={i}")
        page.encoding = page.apparent_encoding
        tree = etree.HTML(page.text)
        li_list = tree.xpath('/html/body/div[3]/div[1]/div/div[1]/ol/li')
        for li in li_list:
            name = li.xpath('./div/div[2]/div[1]/a/span[1]/text()')[0]
            url = li.xpath('./div/div[2]/div[1]/a/@href')[0]
            raw = str(li.xpath('./div/div[2]/div[2]/p[1]/text()[1]')[0]).strip()
            author = raw.split(':')[1].split(" ")[1]
            star = str(raw.split(':')[-1].split(" ")[-1]).replace("...","")

            data_raw = str(li.xpath('./div/div[2]/div[2]/p[1]/text()[2]')[0]).strip()
            year = data_raw.split('/')[0]
            country = data_raw.split('/')[1]
            style = data_raw.split('/')[2]

            score = li.xpath('./div/div[2]/div[2]/div/span[2]/text()')[0]
            count = str(li.xpath('./div/div[2]/div[2]/div/span[4]/text()')[0]).replace("人评价", "")
            print(name, url, author, star, year, country, style, score, count)


