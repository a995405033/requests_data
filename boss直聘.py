import time
import csv
import re
import random
from urllib.parse import quote
from DrissionPage import ChromiumPage


def parse_salary(salary_desc):
    """
    解析薪资描述，提取结构化信息
    
    参数:
        salary_desc: 薪资描述字符串，如 '4-7K', '200-210元/天', '19-20K·16薪', '面议'
    
    返回:
        dict: 包含最低薪资、最高薪资、单位、原始描述等的字典
    """
    original_desc = salary_desc or ''
    
    if not salary_desc or salary_desc == '面议' or '面议' in salary_desc:
        return {
            '薪资原始描述': original_desc,
            '最低薪资(元)': '',
            '最高薪资(元)': '',
            '薪资单位': '',
            '额外信息': ''
        }
    
    # 提取额外信息（如16薪）
    extra_info = ''
    if '·' in salary_desc:
        parts = salary_desc.split('·')
        salary_desc = parts[0]
        extra_info = '·'.join(parts[1:])
    
    # 提取数字范围
    numbers = re.findall(r'[\d.]+', salary_desc)
    
    min_salary = ''
    max_salary = ''
    unit = ''
    
    if len(numbers) >= 2:
        min_salary = numbers[0]
        max_salary = numbers[1]
    elif len(numbers) == 1:
        min_salary = numbers[0]
        max_salary = numbers[0]
    else:
        # 没有找到数字，返回原始描述
        return {
            '薪资原始描述': original_desc,
            '最低薪资(元)': '',
            '最高薪资(元)': '',
            '薪资单位': '',
            '额外信息': extra_info
        }
    
    # 判断单位并转换
    if 'K' in salary_desc.upper() or 'k' in salary_desc:
        unit = 'K/月'
        # 将K转换为元（乘以1000）
        try:
            if min_salary:
                min_salary = str(int(float(min_salary) * 1000))
            if max_salary:
                max_salary = str(int(float(max_salary) * 1000))
        except ValueError:
            pass
    elif '万' in salary_desc:
        unit = '万/月'
        # 将万转换为元（乘以10000）
        try:
            if min_salary:
                min_salary = str(int(float(min_salary) * 10000))
            if max_salary:
                max_salary = str(int(float(max_salary) * 10000))
        except ValueError:
            pass
    elif '元/天' in salary_desc:
        unit = '元/天'
        # 日薪转换为月薪（按22个工作日计算）
        try:
            if min_salary:
                min_salary = str(int(float(min_salary) * 22))
            if max_salary:
                max_salary = str(int(float(max_salary) * 22))
        except ValueError:
            pass
    elif '元/月' in salary_desc:
        unit = '元/月'
    else:
        # 默认假设是元/月（如果只有数字没有单位）
        unit = '元/月'
    
    return {
        '薪资原始描述': original_desc,
        '最低薪资(元)': min_salary,
        '最高薪资(元)': max_salary,
        '薪资单位': unit,
        '额外信息': extra_info
    }


def crawl_boss_jobs(keyword, pages, output_file='boss_jobs.csv'):
    """
    爬取Boss直聘职位数据并保存到CSV文件
    
    参数:
        keyword: 搜索关键词
        pages: 要爬取的页数
        output_file: 输出CSV文件名，默认为'boss_jobs.csv'
    """
    # 初始化浏览器
    dp = ChromiumPage()
    dp.listen.start('wapi/zpgeek/search/joblist.json')
    
    # URL编码关键词
    encoded_keyword = quote(keyword)
    url = f'https://www.zhipin.com/web/geek/jobs?city=100010000&position=120105&query={encoded_keyword}'
    dp.get(url)
    
    # 存储所有职位数据
    all_jobs = []
    
    for page in range(1, pages + 1):
        # 下滑网页页面到底部
        dp.scroll.to_bottom()
        print(f'正在采集第{page}页的数据内容')
        # 等待数据包加载
        res = dp.listen.wait()
        # 获取响应体
        json_data = res.response.body
        
        jobList = json_data['zpData']['jobList']
        
        for index in jobList:
            # 过滤掉包含"实习生"的岗位
            job_name = index.get('jobName', '')
            if '实习生' in job_name:
                continue
            
            # 只爬取薪资中包含"K"的岗位
            salary_desc = index.get('salaryDesc', '')
            if 'K' not in salary_desc.upper():
                continue
            
            # 解析薪资信息
            salary_info = parse_salary(salary_desc)
            
            # 构建职位详情URL
            encrypt_job_id = index.get('encryptJobId', '')
            job_detail_url = f'https://www.zhipin.com/job_detail/{encrypt_job_id}.html' if encrypt_job_id else ''
            
            # 提取职位信息数据
            jobDesc = {
                '职位名称': index.get('jobName', ''),
                '公司名称': index.get('brandName', ''),
                '职位详情URL': job_detail_url,
                '薪资原始描述': salary_info['薪资原始描述'],
                '最低薪资(元)': salary_info['最低薪资(元)'],
                '最高薪资(元)': salary_info['最高薪资(元)'],
                '薪资单位': salary_info['薪资单位'],
                '薪资额外信息': salary_info['额外信息'],
                '城市': index.get('cityName', ''),
                '区域': index.get('areaDistrict', ''),
                '商圈': index.get('businessDistrict', ''),
                '工作经验': index.get('jobExperience', ''),
                '学历要求': index.get('jobDegree', ''),
                '公司行业': index.get('brandIndustry', ''),
                '公司规模': index.get('brandScaleName', ''),
                '融资阶段': index.get('brandStageName', ''),
                '技能要求': ','.join(index.get('skills', [])),
                '福利待遇': ','.join(index.get('welfareList', [])),
                '职位标签': ','.join(index.get('jobLabels', [])),
                '公司LOGO': index.get('brandLogo', ''),
                'Boss姓名': index.get('bossName', ''),
                'Boss职位': index.get('bossTitle', ''),
            }
            
            all_jobs.append(jobDesc)
            print(f"已采集: {jobDesc['职位名称']} - {jobDesc['公司名称']}")
        
        # 如果不是最后一页，随机等待1-5秒再继续
        if page < pages:
            wait_time = random.uniform(1, 5)
            print(f'等待 {wait_time:.2f} 秒后继续翻页...')
            time.sleep(wait_time)
    
    # 保存到CSV文件
    if all_jobs:
        # 定义CSV表头（中文）
        fieldnames = [
            '职位名称', '公司名称', '职位详情URL', '薪资原始描述', '最低薪资(元)', '最高薪资(元)', 
            '薪资单位', '薪资额外信息', '城市', '区域', '商圈',
            '工作经验', '学历要求', '公司行业', '公司规模', '融资阶段',
            '技能要求', '福利待遇', '职位标签', '公司LOGO', 'Boss姓名', 'Boss职位'
        ]
        
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_jobs)
        
        print(f'\n数据已保存到 {output_file}，共采集 {len(all_jobs)} 条职位信息（已过滤实习生岗位）')
    else:
        print('未采集到任何数据')
    
    return all_jobs


# 示例使用
if __name__ == '__main__':
    # 使用示例：爬取"插画师"关键词，爬取2页数据
    crawl_boss_jobs(keyword='插画师', pages=2, output_file='boss_jobs.csv')
