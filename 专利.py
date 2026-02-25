import requests
import json
import time
import random
import base64
import uuid
from datetime import datetime
import csv
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import pandas as pd
import webbrowser
import numpy as np
import cv2
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


class CaptchaSolver:
    """
    自动破解滑块验证码，获取 captchaVerification
    使用 OpenCV 边缘检测 + 模板匹配识别缺口位置
    """

    CAPTCHA_TYPE = "zlcpBlockPuzzle"
    CAPTCHA_GET_URL = "https://api.zlcp.org.cn/opc/api/captcha/get"
    CAPTCHA_CHECK_URL = "https://api.zlcp.org.cn/opc/api/captcha/check"
    COMMON_HEADERS = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.zlcp.org.cn",
        "referer": "https://www.zlcp.org.cn/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, max_retries=5, callback=None):
        """
        :param max_retries: 最大重试次数
        :param callback: 日志回调函数，用于输出到 GUI
        """
        self.max_retries = max_retries
        self.callback = callback

    def _log(self, msg):
        if self.callback:
            self.callback(msg)
        else:
            print(msg.strip())

    @staticmethod
    def _compact_json(obj):
        """生成与 JS JSON.stringify 一致的紧凑 JSON（无空格）"""
        return json.dumps(obj, separators=(",", ":"))

    @staticmethod
    def _aes_ecb_encrypt(plaintext, key):
        """AES-128-ECB 加密（PKCS7 填充），返回 Base64 字符串"""
        key_bytes = key.encode("utf-8")
        cipher = AES.new(key_bytes, AES.MODE_ECB)
        encrypted = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
        return base64.b64encode(encrypted).decode("utf-8")

    @staticmethod
    def _detect_gap_position(bg_b64, slider_b64):
        """使用 OpenCV 检测滑块缺口的 X 坐标"""
        bg_bytes = base64.b64decode(bg_b64)
        slider_bytes = base64.b64decode(slider_b64)

        bg_arr = np.frombuffer(bg_bytes, np.uint8)
        slider_arr = np.frombuffer(slider_bytes, np.uint8)

        bg_img = cv2.imdecode(bg_arr, cv2.IMREAD_COLOR)
        slider_img = cv2.imdecode(slider_arr, cv2.IMREAD_UNCHANGED)

        if bg_img is None or slider_img is None:
            raise ValueError("图片解码失败")

        # 提取滑块非透明区域
        if slider_img.shape[2] == 4:
            alpha = slider_img[:, :, 3]
            slider_bgr = slider_img[:, :, :3]
            rows = np.any(alpha > 0, axis=1)
            cols = np.any(alpha > 0, axis=0)
            if rows.any() and cols.any():
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]
                slider_crop = slider_bgr[rmin:rmax + 1, cmin:cmax + 1]
                mask_crop = alpha[rmin:rmax + 1, cmin:cmax + 1]
            else:
                slider_crop = slider_bgr
                mask_crop = alpha
        else:
            slider_crop = slider_img
            mask_crop = None

        bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
        slider_gray = cv2.cvtColor(slider_crop, cv2.COLOR_BGR2GRAY)

        # 方法1：边缘检测 + 模板匹配
        bg_edge = cv2.Canny(bg_gray, 100, 200)
        slider_edge = cv2.Canny(slider_gray, 100, 200)
        result1 = cv2.matchTemplate(bg_edge, slider_edge, cv2.TM_CCOEFF_NORMED)
        _, max_val1, _, max_loc1 = cv2.minMaxLoc(result1)
        gap_x = max_loc1[0]

        # 方法2：灰度 + mask 模板匹配（通常更准确）
        if mask_crop is not None:
            result2 = cv2.matchTemplate(bg_gray, slider_gray, cv2.TM_CCOEFF_NORMED, mask=mask_crop)
            _, max_val2, _, max_loc2 = cv2.minMaxLoc(result2)
            if max_val2 > max_val1:
                gap_x = max_loc2[0]

        return gap_x

    def solve(self):
        """
        自动获取 captchaVerification

        :return: captchaVerification 字符串，失败返回 None
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                self._log(f"🔐 正在自动获取验证码 (第{attempt}/{self.max_retries}次)...\n")

                # 第1步：获取验证码图片
                client_uid = "slider-" + str(uuid.uuid4())
                get_resp = requests.post(
                    self.CAPTCHA_GET_URL,
                    headers=self.COMMON_HEADERS,
                    json={
                        "captchaType": self.CAPTCHA_TYPE,
                        "clientUid": client_uid,
                        "ts": int(time.time() * 1000)
                    },
                    timeout=15
                )
                if not get_resp.text.strip():
                    self._log(f"  ❌ 获取验证码图片失败（响应为空）\n")
                    time.sleep(2)
                    continue

                get_data = get_resp.json()
                captcha_data = get_data.get("data") or get_data.get("repData")
                if not captcha_data:
                    self._log(f"  ❌ 获取验证码失败: {get_data.get('message', '')}\n")
                    time.sleep(2)
                    continue

                token = captcha_data["token"]
                secret_key = captcha_data["secretKey"]
                bg_b64 = captcha_data["originalImageBase64"]
                slider_b64 = captcha_data["jigsawImageBase64"]

                # 第2步：识别缺口位置
                gap_x = self._detect_gap_position(bg_b64, slider_b64)
                self._log(f"  识别缺口位置: x={gap_x}\n")

                # 模拟人类延迟
                time.sleep(1)

                # 第3步：AES 加密并校验
                point = {"x": gap_x, "y": 5}
                point_json_str = self._compact_json(point)
                encrypted_point = self._aes_ecb_encrypt(point_json_str, secret_key)

                check_resp = requests.post(
                    self.CAPTCHA_CHECK_URL,
                    headers=self.COMMON_HEADERS,
                    json={
                        "captchaType": self.CAPTCHA_TYPE,
                        "pointJson": encrypted_point,
                        "token": token
                    },
                    timeout=15
                )
                check_data = check_resp.json()
                check_code = check_data.get("code", check_data.get("repCode"))

                if check_code != 0 and check_code != "0000":
                    self._log(f"  ❌ 校验失败: {check_data.get('message', '')}\n")
                    time.sleep(2)
                    continue

                # 第4步：生成 captchaVerification
                raw = token + "---" + self._compact_json({"x": gap_x, "y": 5})
                captcha_verification = self._aes_ecb_encrypt(raw, secret_key)

                self._log(f"  ✅ 验证码获取成功！\n")
                return captcha_verification

            except Exception as e:
                self._log(f"  ❌ 第{attempt}次尝试出错: {e}\n")
                time.sleep(2)

        self._log(f"❌ {self.max_retries}次尝试全部失败，无法自动获取验证码\n")
        return None


def get_product_detail(product_guid, verify_year, headers, request_counter=None, current_count_ref=None):
    """
    获取产品详情页数据

    :param product_guid: 产品GUID
    :param verify_year: 认定年度（用于请求参数y）
    :param headers: 请求头
    :return: 详情页JSON数据，如果失败返回None，如果需要更新验证码返回'NEED_UPDATE_CAPTCHA'
    """
    detail_url = f"https://api.zlcp.org.cn/eszlcp/api/es/pro/detail?productGuid={product_guid}&y={verify_year}"

    # 请求体
    payload = {
        "productGuid": product_guid,
        "y": verify_year
    }

    try:
        # 先尝试JSON格式（与列表接口一致）
        response = requests.post(detail_url, headers=headers, json=payload, timeout=30)

        # 更新请求计数
        if request_counter and current_count_ref:
            current_count_ref[0] += 1
            request_counter(current_count_ref[0])

        response.raise_for_status()
        detail_data = response.json()
        if detail_data.get('code') == 0:
            data = detail_data.get('data')
            if data:
                # 检查是否有patList
                pat_list = data.get('patList', [])
                pat_total = data.get('patTotal', 0) or data.get('patCount', 0)
                if isinstance(pat_list, list):
                    print(f"    详情数据获取成功，patTotal={pat_total}，实际返回 {len(pat_list)} 条专利")
                return data
            else:
                print(f"    警告：详情数据为空 (productGuid: {product_guid})")
                return None
        else:
            # 检查是否是验证码错误
            error_code = detail_data.get('code')
            error_msg = detail_data.get('message', '')
            if error_code != 0:
                print(
                    f"    警告：详情接口返回错误 (productGuid: {product_guid}, code: {error_code}, message: {error_msg})")
                # 如果返回错误码，可能需要更新验证码
                if '验证' in error_msg or 'captcha' in error_msg.lower() or error_code in [401, 403]:
                    return 'NEED_UPDATE_CAPTCHA'
            return None
    except requests.exceptions.HTTPError as e:
        # HTTP错误，可能是验证码问题
        if e.response and e.response.status_code in [401, 403]:
            print(f"    HTTP错误：可能需要更新验证码 (productGuid: {product_guid}, status: {e.response.status_code})")
            return 'NEED_UPDATE_CAPTCHA'
        raise
    except Exception as e:
        # 如果JSON格式失败，尝试表单格式
        try:
            detail_headers = headers.copy()
            detail_headers['content-type'] = 'application/x-www-form-urlencoded'
            response = requests.post(detail_url, headers=detail_headers, data=payload, timeout=30)

            # 更新请求计数
            if request_counter and current_count_ref:
                current_count_ref[0] += 1
                request_counter(current_count_ref[0])

            response.raise_for_status()
            detail_data = response.json()
            if detail_data.get('code') == 0:
                data = detail_data.get('data')
                if data:
                    pat_list = data.get('patList', [])
                    pat_total = data.get('patTotal', 0) or data.get('patCount', 0)
                    if isinstance(pat_list, list):
                        print(f"    详情数据获取成功（表单格式），patTotal={pat_total}，实际返回 {len(pat_list)} 条专利")
                    return data
                return None
            else:
                error_code = detail_data.get('code')
                error_msg = detail_data.get('message', '')
                if '验证' in error_msg or 'captcha' in error_msg.lower() or error_code in [401, 403]:
                    return 'NEED_UPDATE_CAPTCHA'
        except requests.exceptions.HTTPError as e2:
            if e2.response and e2.response.status_code in [401, 403]:
                return 'NEED_UPDATE_CAPTCHA'
        except Exception as e2:
            print(f"获取产品详情失败 (productGuid: {product_guid}): JSON格式错误: {e}, 表单格式错误: {e2}")

    return None


def format_list_value(value):
    """
    格式化列表值，用逗号分隔
    """
    if value is None:
        return ''
    if isinstance(value, list):
        # 过滤掉None值，然后转换为字符串并用逗号连接
        return ','.join([str(item) for item in value if item is not None])
    return str(value)


def format_year_list_value(value):
    """
    格式化年份列表值，用顿号（、）分隔
    用于recordVerifyYearList和recordYearList
    """
    if value is None:
        return ''
    if isinstance(value, list):
        # 过滤掉None值，然后转换为字符串并用顿号连接
        return '、'.join([str(item) for item in value if item is not None])
    return str(value)


def extract_product_data(json_data, all_data, all_patents, headers,
                         need_detail=True, product_csv=None, patent_csv=None, product_headers=None, patent_headers=None,
                         product_base_headers=None, product_file_initialized_ref=None, callback=None,
                         request_counter=None, current_count_ref=None, extra_fields=None):
    """
    从JSON响应中提取产品数据，如果缺少字段则从详情页获取

    :param json_data: API返回的JSON数据
    :param all_data: 存储所有产品数据的列表
    :param all_patents: 存储所有专利数据的列表
    :param headers: 请求头（用于获取详情）
    :param need_detail: 是否需要获取详情页数据
    :param product_csv: 产品CSV文件路径，用于实时写入
    :param patent_csv: 专利CSV文件路径，用于实时写入
    :param product_headers: 产品CSV表头列表（会被动态更新）
    :param patent_headers: 专利CSV表头列表
    :param product_base_headers: 产品CSV基础表头列表
    :param product_file_initialized_ref: 产品文件初始化状态（字典引用，用于修改状态）
    :param extra_fields: 额外字段字典，会被添加到每条产品记录中（如 {'查询公司': '某公司'}）
    :return: 返回处理的产品数量，如果需要更新验证码返回'NEED_UPDATE_CAPTCHA'
    """
    try:
        if json_data.get('code') == 0 and json_data.get('data'):
            data = json_data['data']
            if 'list' in data and isinstance(data['list'], list):
                products = data['list']
                for idx, product in enumerate(products):
                    product_guid = product.get('productGuid', '')
                    verify_year = product.get('productVerifyYear', 2025)
                    product_name = product.get('productName', '')
                    product_num = product.get('productNum', '')

                    # 构建产品链接（先使用认定年度，获取详情后会更新）
                    product_link = f"https://www.zlcp.org.cn/search/{product_guid}?y={verify_year}&isPub" if product_guid else ""

                    # 基础字段：保留中文表头的字段
                    product_row = {
                        '产品名称': product_name,
                        '产品备案号': product_num,
                        '产品链接': product_link
                    }

                    # 添加额外字段（如查询公司）
                    if extra_fields:
                        product_row.update(extra_fields)

                    # 先从列表数据中提取所有字段（除了patList和已处理的基础字段）
                    for key, value in product.items():
                        if key in ['productName', 'productNum']:
                            continue  # 已经作为中文表头处理过了
                        if key == 'patList':
                            continue  # patList单独处理，不添加到产品数据中
                        if isinstance(value, list):
                            # 年份列表使用顿号分隔
                            if key in ['recordVerifyYearList', 'recordYearList', 'authYearList']:
                                product_row[key] = format_year_list_value(value)
                            # 对于复杂对象列表（如imageList, fileList），转换为JSON字符串
                            elif value and isinstance(value[0], dict):
                                product_row[key] = json.dumps(value, ensure_ascii=False)
                            else:
                                product_row[key] = format_list_value(value)
                        elif isinstance(value, dict):
                            # 字典类型转换为JSON字符串
                            product_row[key] = json.dumps(value, ensure_ascii=False) if value else ''
                        else:
                            product_row[key] = value if value is not None else ''

                    # 初始化detail_data变量
                    detail_data = None

                    # 始终获取详情接口以拿到完整字段（entModel, fileList, imageList等）
                    if need_detail and product_guid:
                        # 第一步：先用当前年份获取基本信息，以获取recordVerifyYearList
                        msg = f"    正在获取产品详情以确定认定年份...\n"
                        if callback:
                            callback(msg)
                        else:
                            print(msg.strip())
                        initial_detail_data = get_product_detail(product_guid, verify_year, headers, request_counter,
                                                                 current_count_ref)

                        # 检查是否需要更新验证码
                        if initial_detail_data == 'NEED_UPDATE_CAPTCHA':
                            print(f"    详情接口返回错误，需要更新验证码")
                            return 'NEED_UPDATE_CAPTCHA'

                        if initial_detail_data and isinstance(initial_detail_data, dict):
                            # 第二步：检查是否有recordVerifyYearList，遍历每个年份获取完整数据
                            record_verify_years = initial_detail_data.get('recordVerifyYearList', [])

                            if record_verify_years and isinstance(record_verify_years, list) and len(
                                    record_verify_years) > 0:
                                msg = f"    ✅ 发现 {len(record_verify_years)} 个认定年份: {record_verify_years}，开始逐年获取数据\n"
                                if callback:
                                    callback(msg)
                                else:
                                    print(msg.strip())

                                # 遍历每个年份，为每个年份创建一条产品记录
                                for year_idx, year in enumerate(record_verify_years):
                                    msg = f"    [{year_idx + 1}/{len(record_verify_years)}] 正在获取 {year} 年度的产品和专利数据...\n"
                                    if callback:
                                        callback(msg)
                                    else:
                                        print(msg.strip())
                                    year_detail_data = get_product_detail(product_guid, year, headers, request_counter,
                                                                          current_count_ref)

                                    if year_detail_data == 'NEED_UPDATE_CAPTCHA':
                                        msg = f"    获取 {year} 年度数据时验证码失效\n"
                                        if callback:
                                            callback(msg)
                                        else:
                                            print(msg.strip())
                                        return 'NEED_UPDATE_CAPTCHA'

                                    if year_detail_data and isinstance(year_detail_data, dict):
                                        # 为该年份创建产品记录
                                        year_product_row = {
                                            '产品名称': product_name,
                                            '产品备案号': product_num,
                                            '产品链接': f"https://www.zlcp.org.cn/search/{product_guid}?y={year}&isPub",
                                            '认定年份': year  # 添加认定年份字段
                                        }

                                        # 添加额外字段（如查询公司）
                                        if extra_fields:
                                            year_product_row.update(extra_fields)

                                        # 添加该年份的所有产品字段（详情接口的完整字段）
                                        for key, value in year_detail_data.items():
                                            if key == 'patList':
                                                continue  # patList单独处理

                                            # 处理列表字段
                                            if isinstance(value, list):
                                                if key in ['recordVerifyYearList', 'recordYearList', 'authYearList']:
                                                    year_product_row[key] = format_year_list_value(value)
                                                elif value and isinstance(value[0], dict):
                                                    year_product_row[key] = json.dumps(value, ensure_ascii=False)
                                                else:
                                                    year_product_row[key] = format_list_value(value)
                                            # 处理字典字段
                                            elif isinstance(value, dict):
                                                if key == 'entModel':
                                                    for ent_key, ent_value in value.items():
                                                        year_product_row[
                                                            f'entModel_{ent_key}'] = ent_value if ent_value is not None else ''
                                                else:
                                                    year_product_row[key] = json.dumps(value,
                                                                                       ensure_ascii=False) if value else ''
                                            else:
                                                year_product_row[key] = value if value is not None else ''

                                        # 保存该年份的产品记录
                                        all_data.append(year_product_row)

                                        # 实时写入该年份的产品到CSV
                                        if product_csv:
                                            # 收集当前所有字段名
                                            all_field_names = set()
                                            for row in all_data:
                                                all_field_names.update(row.keys())

                                            if product_base_headers:
                                                new_headers = product_base_headers + ['认定年份'] + [f for f in sorted(
                                                    all_field_names) if
                                                                                                     f not in product_base_headers and f != '认定年份']
                                            else:
                                                new_headers = sorted(all_field_names)

                                            old_headers = product_file_initialized_ref.get('headers',
                                                                                           []) if product_file_initialized_ref else []
                                            need_rebuild = product_file_initialized_ref and product_file_initialized_ref.get(
                                                'initialized', False) and set(new_headers) - set(old_headers)

                                            if not product_file_initialized_ref.get('initialized',
                                                                                    False) or need_rebuild:
                                                # 首次初始化，或者新数据有更多字段需要重建CSV
                                                try:
                                                    existing_rows = []
                                                    if need_rebuild and os.path.exists(product_csv):
                                                        with open(product_csv, 'r', encoding='gbk',
                                                                  errors='ignore') as csvfile:
                                                            reader = csv.DictReader(csvfile)
                                                            for r in reader:
                                                                existing_rows.append(r)
                                                    with open(product_csv, 'w', newline='', encoding='gbk',
                                                              errors='ignore') as csvfile:
                                                        writer = csv.DictWriter(csvfile, fieldnames=new_headers)
                                                        writer.writeheader()
                                                        for r in existing_rows:
                                                            clean_r = {k: str(r.get(k, '')) for k in new_headers}
                                                            writer.writerow(clean_r)
                                                    product_file_initialized_ref['initialized'] = True
                                                    product_file_initialized_ref['headers'] = new_headers
                                                    product_headers = new_headers
                                                except Exception as e:
                                                    print(f"    初始化/重建产品CSV失败: {e}")
                                            else:
                                                product_headers = old_headers

                                            if product_headers:
                                                try:
                                                    with open(product_csv, 'a', newline='', encoding='gbk',
                                                              errors='ignore') as csvfile:
                                                        writer = csv.DictWriter(csvfile, fieldnames=product_headers)
                                                        clean_row = {}
                                                        for key in product_headers:
                                                            value = year_product_row.get(key, '')
                                                            clean_row[key] = str(value) if value is not None else ''
                                                        writer.writerow(clean_row)
                                                except Exception as e:
                                                    print(f"    写入产品CSV失败: {e}")

                                        # 处理该年份的专利数据
                                        year_pat_list = year_detail_data.get('patList', [])
                                        year_pat_total = year_detail_data.get('patTotal') or year_detail_data.get(
                                            'patCount') or ''

                                        if year_pat_list and isinstance(year_pat_list, list):
                                            msg = f"      ✓ {year} 年度获取到 {len(year_pat_list)} 条专利，patTotal={year_pat_total}\n"
                                            if callback:
                                                callback(msg)
                                            else:
                                                print(msg.strip())
                                            for pat in year_pat_list:
                                                if isinstance(pat, dict):
                                                    patent_row = {
                                                        '产品名称': product_name,
                                                        '产品备案号': product_num,
                                                        '产品链接': year_product_row['产品链接'],
                                                        'patTotal': year_pat_total,
                                                        '认定年份': year  # 添加认定年份字段
                                                    }
                                                    # 添加patList中的所有字段
                                                    for pat_key, pat_value in pat.items():
                                                        patent_row[pat_key] = pat_value if pat_value is not None else ''

                                                    all_patents.append(patent_row)

                                                    # 实时写入专利到CSV
                                                    if patent_csv and patent_headers:
                                                        try:
                                                            with open(patent_csv, 'a', newline='', encoding='gbk',
                                                                      errors='ignore') as csvfile:
                                                                writer = csv.DictWriter(csvfile,
                                                                                        fieldnames=patent_headers)
                                                                clean_row = {}
                                                                for key in patent_headers:
                                                                    value = patent_row.get(key, '')
                                                                    clean_row[key] = str(
                                                                        value) if value is not None else ''
                                                                writer.writerow(clean_row)
                                                        except Exception as e:
                                                            print(f"      写入专利CSV失败: {e}")

                                msg = f"    ✅ 已完成 {len(record_verify_years)} 个年份的数据获取\n"
                                if callback:
                                    callback(msg)
                                else:
                                    print(msg.strip())
                                # 多年份情况：已经在循环中保存了每个年份的数据，不需要再保存product_row
                            else:
                                # 如果没有多年份数据，使用initial_detail_data作为单一产品记录
                                detail_data = initial_detail_data

                                # 更新产品链接：使用首次备案年份
                                product_year = detail_data.get('productYear', verify_year)
                                product_row[
                                    '产品链接'] = f"https://www.zlcp.org.cn/search/{product_guid}?y={product_year}&isPub"

                                # 处理详情数据中的patList
                                detail_pat_list = detail_data.get('patList', [])
                                # 获取patTotal（优先从detail_data获取，否则从product_row获取）
                                detail_pat_total = detail_data.get('patTotal') or detail_data.get(
                                    'patCount') or product_row.get('patTotal', '')
                                if isinstance(detail_pat_list, list) and len(detail_pat_list) > 0:
                                    for pat in detail_pat_list:
                                        if isinstance(pat, dict):
                                            patent_row = {
                                                '产品名称': product_name,
                                                '产品备案号': product_num,
                                                '产品链接': product_row['产品链接'],
                                                'patTotal': detail_pat_total
                                            }
                                            # 添加patList中的所有字段
                                            for pat_key, pat_value in pat.items():
                                                patent_row[pat_key] = pat_value if pat_value is not None else ''

                                            all_patents.append(patent_row)

                                            # 实时写入专利到CSV
                                            if patent_csv and patent_headers:
                                                try:
                                                    with open(patent_csv, 'a', newline='', encoding='gbk',
                                                              errors='ignore') as csvfile:
                                                        writer = csv.DictWriter(csvfile, fieldnames=patent_headers)
                                                        clean_row = {}
                                                        for key in patent_headers:
                                                            value = patent_row.get(key, '')
                                                            clean_row[key] = str(value) if value is not None else ''
                                                        writer.writerow(clean_row)
                                                except Exception as e:
                                                    print(f"      写入专利CSV失败: {e}")

                                # 遍历detail_data的所有字段，用详情数据补充或覆盖列表数据
                                for key, value in detail_data.items():
                                    if key == 'patList':
                                        continue  # 已经处理过了，跳过

                                    # 处理列表字段
                                    if isinstance(value, list):
                                        if key in ['recordVerifyYearList', 'recordYearList', 'authYearList']:
                                            product_row[key] = format_year_list_value(value)
                                        elif value and isinstance(value[0], dict):
                                            product_row[key] = json.dumps(value, ensure_ascii=False)
                                        else:
                                            product_row[key] = format_list_value(value)
                                    # 处理字典字段
                                    elif isinstance(value, dict):
                                        if key == 'entModel':
                                            for ent_key, ent_value in value.items():
                                                product_row[
                                                    f'entModel_{ent_key}'] = ent_value if ent_value is not None else ''
                                        else:
                                            product_row[key] = json.dumps(value, ensure_ascii=False) if value else ''
                                    else:
                                        product_row[key] = value if value is not None else ''

                                # 单年份情况：保存product_row
                                all_data.append(product_row)

                                # 实时写入产品到CSV
                                if product_csv:
                                    # 收集当前所有字段名
                                    all_field_names = set()
                                    for row in all_data:
                                        all_field_names.update(row.keys())

                                    if product_base_headers:
                                        new_headers = product_base_headers + [f for f in sorted(all_field_names) if
                                                                              f not in product_base_headers]
                                    else:
                                        new_headers = sorted(all_field_names)

                                    old_headers = product_file_initialized_ref.get('headers',
                                                                                   []) if product_file_initialized_ref else []
                                    need_rebuild = product_file_initialized_ref and product_file_initialized_ref.get(
                                        'initialized', False) and set(new_headers) - set(old_headers)

                                    if not product_file_initialized_ref.get('initialized', False) or need_rebuild:
                                        # 首次初始化，或者新数据有更多字段需要重建CSV
                                        try:
                                            existing_rows = []
                                            if need_rebuild and os.path.exists(product_csv):
                                                with open(product_csv, 'r', encoding='gbk', errors='ignore') as csvfile:
                                                    reader = csv.DictReader(csvfile)
                                                    for r in reader:
                                                        existing_rows.append(r)
                                            with open(product_csv, 'w', newline='', encoding='gbk',
                                                      errors='ignore') as csvfile:
                                                writer = csv.DictWriter(csvfile, fieldnames=new_headers)
                                                writer.writeheader()
                                                for r in existing_rows:
                                                    clean_r = {k: str(r.get(k, '')) for k in new_headers}
                                                    writer.writerow(clean_r)
                                            product_file_initialized_ref['initialized'] = True
                                            product_file_initialized_ref['headers'] = new_headers
                                            product_headers = new_headers
                                        except Exception as e:
                                            print(f"    初始化/重建产品CSV失败: {e}")
                                    else:
                                        product_headers = old_headers

                                    if product_headers:
                                        try:
                                            with open(product_csv, 'a', newline='', encoding='gbk',
                                                      errors='ignore') as csvfile:
                                                writer = csv.DictWriter(csvfile, fieldnames=product_headers)
                                                clean_row = {}
                                                for key in product_headers:
                                                    value = product_row.get(key, '')
                                                    clean_row[key] = str(value) if value is not None else ''
                                                writer.writerow(clean_row)
                                        except Exception as e:
                                            print(f"    写入产品CSV失败: {e}")
                        else:
                            print(f"    警告：无法获取产品详情数据 (productGuid: {product_guid})")

                    print(f"  已处理产品 {idx + 1}/{len(products)}: {product_name}")

                return len(products)
    except Exception as e:
        print(f"提取数据时出错: {e}")
        import traceback
        traceback.print_exc()
    return 0


# 移除load_existing_records函数，不再需要读取文件初始化


def get_headers(captchaverification):
    """
    获取请求头

    :param captchaverification: 验证码参数
    :return: 请求头字典
    """
    return {
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "zh-CN,zh;q=0.9",
        "captchaverification": captchaverification,
        "connection": "keep-alive",
        "content-type": "application/json;charset=UTF-8",
        "host": "api.zlcp.org.cn",
        "origin": "https://www.zlcp.org.cn",
        "referer": "https://www.zlcp.org.cn/",
        "sec-ch-ua": '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    }


def crawl_patents(start_page=1, end_page=None, limit=10, captchaverification=None,
                  save_dir=None, max_pages_per_captcha=100, callback=None, stop_check=None,
                  request_counter=None, current_count=0, product_csv=None, patent_csv=None):
    """
    爬取专利数据并保存到CSV文件

    :param start_page: 起始页码，默认为1
    :param end_page: 结束页码，None表示只爬取一页
    :param limit: 每页数量，默认为10
    :param captchaverification: 验证码参数
    :param save_dir: 保存目录，None表示使用当前目录
    :param max_pages_per_captcha: 每个验证码最多爬取的页数
    :param callback: 回调函数，用于更新GUI状态
    :param stop_check: 停止检查函数，返回True表示需要停止
    :param product_csv: 产品CSV文件路径（可选，如果提供则使用该文件）
    :param patent_csv: 专利CSV文件路径（可选，如果提供则使用该文件）
    :return: 返回所有爬取的数据列表，如果需要更新验证码返回'NEED_UPDATE_CAPTCHA'
    """
    # 如果没有指定结束页，只爬取一页
    if end_page is None:
        end_page = start_page

    # 确定保存目录
    if save_dir is None:
        save_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        os.makedirs(save_dir, exist_ok=True)

    # 如果没有提供文件名，则生成新的
    if product_csv is None or patent_csv is None:
        # 生成时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 根据页数范围生成文件名（使用绝对路径，带时间戳）
        if start_page == end_page:
            product_csv = os.path.join(save_dir, f'产品_第{start_page}页_{timestamp}.csv')
            patent_csv = os.path.join(save_dir, f'专利_第{start_page}页_{timestamp}.csv')
        else:
            product_csv = os.path.join(save_dir, f'产品_第{start_page}-{end_page}页_{timestamp}.csv')
            patent_csv = os.path.join(save_dir, f'专利_第{start_page}-{end_page}页_{timestamp}.csv')

    if callback:
        callback(f"数据将保存到: {product_csv} 和 {patent_csv}\n")
    else:
        print(f"数据将保存到: {product_csv} 和 {patent_csv}")

    url = "https://api.zlcp.org.cn/eszlcp/api/es/pro/page"

    # 请求头
    headers = get_headers(captchaverification)

    all_data = []
    all_patents = []
    current_page = start_page
    pages_crawled = 0

    # 产品CSV表头：固定保留的中文表头
    product_base_headers = ['产品名称', '产品备案号', '产品链接']

    # 专利CSV表头：固定保留的中文表头 + 认定年份 + patTotal + patList的字段
    patent_base_headers = ['产品名称', '产品备案号', '产品链接', '认定年份']
    patent_field_headers = ['patTotal', 'num', 'name', 'type', 'isCore', 'isAuthShow', 'litigationNO', 'ad', 'apd',
                            'contribution']
    patent_headers = patent_base_headers + patent_field_headers

    # 初始化产品CSV文件（先只写固定表头，动态字段会在第一次写入时确定）
    # 使用字典引用以便在函数内部修改状态
    product_file_initialized_ref = {'initialized': False, 'headers': None}

    # 检查专利CSV文件是否存在
    if os.path.exists(patent_csv):
        if callback:
            callback(f"将追加数据到 {patent_csv}\n")
        else:
            print(f"将追加数据到 {patent_csv}")
    else:
        if callback:
            callback(f"创建新文件: {patent_csv}\n")
        else:
            print(f"创建新文件: {patent_csv}")
        with open(patent_csv, 'w', newline='', encoding='gbk', errors='ignore') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=patent_headers)
            writer.writeheader()

    # 检查产品CSV文件是否存在
    if os.path.exists(product_csv):
        if callback:
            callback(f"将追加数据到 {product_csv}\n")
        else:
            print(f"将追加数据到 {product_csv}")
        # 读取现有表头，用于追加时保持一致
        try:
            with open(product_csv, 'r', encoding='gbk', errors='ignore') as csvfile:
                reader = csv.DictReader(csvfile)
                if reader.fieldnames:
                    product_file_initialized_ref['initialized'] = True
                    product_file_initialized_ref['headers'] = list(reader.fieldnames)
        except Exception as e:
            if callback:
                callback(f"读取产品CSV表头失败: {e}\n")
            else:
                print(f"读取产品CSV表头失败: {e}")
    else:
        if callback:
            callback(f"创建新文件: {product_csv}\n")
        else:
            print(f"创建新文件: {product_csv}")

    while current_page <= end_page:
        # 检查是否需要停止
        if stop_check and stop_check():
            if callback:
                callback(f"\n⏹️ 用户停止爬取\n")
            return 'STOPPED', all_data, all_patents

        # 检查是否超过每个验证码的最大页数限制
        if pages_crawled >= max_pages_per_captcha:
            if callback:
                callback(f"\n⚠️ 已达到每个验证码的最大页数限制 ({max_pages_per_captcha} 页)\n")
            else:
                print(f"\n⚠️ 已达到每个验证码的最大页数限制 ({max_pages_per_captcha} 页)")
            return 'NEED_UPDATE_CAPTCHA', all_data, all_patents

        # 请求体
        payload = {
            "isPub": None,
            "limit": limit,
            "page": current_page,
            "query": "*",
            "proSort": "Score",
            "queryRange": "All",
            "proUnspscCode": "",
            "queryDateBegin": None,
            "queryDateEnd": None,
            "queryDateType": 0,
            "areaCode": ""
        }

        try:
            msg = f"正在爬取第 {current_page} 页数据...\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())

            # 发送POST请求
            response = requests.post(url, headers=headers, json=payload, timeout=30)

            # 更新请求计数
            if request_counter:
                current_count += 1
                request_counter(current_count)

            # 检查响应状态
            response.raise_for_status()

            # 解析JSON响应
            json_data = response.json()

            # 提取产品数据（传入headers用于获取详情）
            prev_data_count = len(all_data)
            prev_patents_count = len(all_patents)

            count = extract_product_data(
                json_data, all_data, all_patents, headers,
                need_detail=True,
                product_csv=product_csv,
                patent_csv=patent_csv,
                product_headers=product_file_initialized_ref.get('headers'),
                patent_headers=patent_headers,
                product_base_headers=product_base_headers,
                product_file_initialized_ref=product_file_initialized_ref,
                callback=callback,
                request_counter=request_counter,
                current_count_ref=[current_count]
            )

            # 更新current_count（从引用中获取最新值）
            if request_counter:
                # 注意：这里不需要更新，因为已经在extract_product_data中更新了
                pass

            # 检查是否需要更新验证码
            if count == 'NEED_UPDATE_CAPTCHA':
                msg = f"\n❌ 验证码已失效！程序停止\n📊 已成功爬取到第 {current_page - 1} 页\n📦 共获取 {len(all_data)} 条产品数据\n📄 共获取 {len(all_patents)} 条专利数据\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
                return 'NEED_UPDATE_CAPTCHA', all_data, all_patents

            if count > 0:
                pages_crawled += 1
                msg = f"第 {current_page} 页获取到 {count} 条产品数据，{len(all_patents) - prev_patents_count} 条专利数据\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
            else:
                msg = f"第 {current_page} 页没有数据，停止爬取\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
                break

            current_page += 1

        except requests.exceptions.RequestException as e:
            msg = f"请求第 {current_page} 页时出错: {e}\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())
            break
        except json.JSONDecodeError as e:
            msg = f"解析第 {current_page} 页JSON数据时出错: {e}\n响应内容: {response.text[:500]}\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())
            break
        except Exception as e:
            msg = f"处理第 {current_page} 页数据时出错: {e}\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())
            import traceback
            traceback.print_exc()
            break

    msg = f"\n总共爬取 {len(all_data)} 条产品数据，{len(all_patents)} 条专利数据\n产品数据已保存到 {product_csv}\n专利数据已保存到 {patent_csv}\n"
    if callback:
        callback(msg)
    else:
        print(msg.strip())
    return None, all_data, all_patents


def crawl_by_registration_numbers(registration_numbers, captchaverification=None,
                                  save_dir=None, max_numbers_per_captcha=1000, callback=None, stop_check=None,
                                  request_counter=None, current_count=0, product_csv=None, patent_csv=None):
    """
    按备案号爬取专利数据并保存到CSV文件

    :param registration_numbers: 备案号列表
    :param captchaverification: 验证码参数
    :param save_dir: 保存目录，None表示使用当前目录
    :param max_numbers_per_captcha: 每个验证码最多爬取的备案号数量
    :param callback: 回调函数，用于更新GUI状态
    :param stop_check: 停止检查函数，返回True表示需要停止
    :param product_csv: 产品CSV文件路径（可选，如果提供则使用该文件）
    :param patent_csv: 专利CSV文件路径（可选，如果提供则使用该文件）
    :return: 返回所有爬取的数据列表，如果需要更新验证码返回'NEED_UPDATE_CAPTCHA'
    """
    # 确定保存目录
    if save_dir is None:
        save_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        os.makedirs(save_dir, exist_ok=True)

    # 如果没有提供文件名，则生成新的
    if product_csv is None or patent_csv is None:
        # 生成时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 生成文件名（带时间戳）
        product_csv = os.path.join(save_dir, f'产品_按备案号_{timestamp}.csv')
        patent_csv = os.path.join(save_dir, f'专利_按备案号_{timestamp}.csv')

    if callback:
        callback(f"数据将保存到: {product_csv} 和 {patent_csv}\n")
        callback(f"共需要爬取 {len(registration_numbers)} 个备案号\n")
    else:
        print(f"数据将保存到: {product_csv} 和 {patent_csv}")
        print(f"共需要爬取 {len(registration_numbers)} 个备案号")

    url = "https://api.zlcp.org.cn/eszlcp/api/es/pro/page"

    # 请求头
    headers = get_headers(captchaverification)

    all_data = []
    all_patents = []
    numbers_crawled = 0

    # 产品CSV表头：固定保留的中文表头
    product_base_headers = ['产品名称', '产品备案号', '产品链接']

    # 专利CSV表头：固定保留的中文表头 + 认定年份 + patTotal + patList的字段
    patent_base_headers = ['产品名称', '产品备案号', '产品链接', '认定年份']
    patent_field_headers = ['patTotal', 'num', 'name', 'type', 'isCore', 'isAuthShow', 'litigationNO', 'ad', 'apd',
                            'contribution']
    patent_headers = patent_base_headers + patent_field_headers

    # 初始化产品CSV文件
    product_file_initialized_ref = {'initialized': False, 'headers': None}

    # 检查专利CSV文件是否存在
    if os.path.exists(patent_csv):
        if callback:
            callback(f"将追加数据到 {patent_csv}\n")
        else:
            print(f"将追加数据到 {patent_csv}")
    else:
        if callback:
            callback(f"创建新文件: {patent_csv}\n")
        else:
            print(f"创建新文件: {patent_csv}")
        with open(patent_csv, 'w', newline='', encoding='gbk', errors='ignore') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=patent_headers)
            writer.writeheader()

    # 检查产品CSV文件是否存在
    if os.path.exists(product_csv):
        if callback:
            callback(f"将追加数据到 {product_csv}\n")
        else:
            print(f"将追加数据到 {product_csv}")
        try:
            with open(product_csv, 'r', encoding='gbk', errors='ignore') as csvfile:
                reader = csv.DictReader(csvfile)
                if reader.fieldnames:
                    product_file_initialized_ref['initialized'] = True
                    product_file_initialized_ref['headers'] = list(reader.fieldnames)
        except Exception as e:
            if callback:
                callback(f"读取产品CSV表头失败: {e}\n")
            else:
                print(f"读取产品CSV表头失败: {e}")
    else:
        if callback:
            callback(f"创建新文件: {product_csv}\n")
        else:
            print(f"创建新文件: {product_csv}")

    for idx, reg_num in enumerate(registration_numbers):
        # 检查是否需要停止
        if stop_check and stop_check():
            if callback:
                callback(f"\n⏹️ 用户停止爬取\n")
            return 'STOPPED', all_data, all_patents

        # 检查是否超过每个验证码的最大备案号数量限制
        if numbers_crawled >= max_numbers_per_captcha:
            if callback:
                callback(f"\n⚠️ 已达到每个验证码的最大备案号数量限制 ({max_numbers_per_captcha} 个)\n")
            else:
                print(f"\n⚠️ 已达到每个验证码的最大备案号数量限制 ({max_numbers_per_captcha} 个)")
            return 'NEED_UPDATE_CAPTCHA', all_data, all_patents

        # 清理备案号（去除空格等）
        reg_num = str(reg_num).strip()
        if not reg_num:
            continue

        # 请求体 - 使用备案号作为查询条件
        payload = {
            "isPub": None,
            "limit": 10,
            "page": 1,
            "query": reg_num,
            "proSort": "Score",
            "queryRange": "All",
            "proUnspscCode": "",
            "queryDateBegin": None,
            "queryDateEnd": None,
            "queryDateType": 0,
            "areaCode": ""
        }

        try:
            msg = f"正在爬取备案号 {reg_num} ({idx + 1}/{len(registration_numbers)})...\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())

            # 发送POST请求
            response = requests.post(url, headers=headers, json=payload, timeout=30)

            # 更新请求计数
            if request_counter:
                current_count += 1
                request_counter(current_count)

            # 检查响应状态
            response.raise_for_status()

            # 解析JSON响应
            json_data = response.json()

            # 提取产品数据
            prev_data_count = len(all_data)
            prev_patents_count = len(all_patents)

            count = extract_product_data(
                json_data, all_data, all_patents, headers,
                need_detail=True,
                product_csv=product_csv,
                patent_csv=patent_csv,
                product_headers=product_file_initialized_ref.get('headers'),
                patent_headers=patent_headers,
                product_base_headers=product_base_headers,
                product_file_initialized_ref=product_file_initialized_ref,
                callback=callback,
                request_counter=request_counter,
                current_count_ref=[current_count]
            )

            # 检查是否需要更新验证码
            if count == 'NEED_UPDATE_CAPTCHA':
                msg = f"\n❌ 验证码已失效！程序停止\n📊 已成功爬取 {idx} 个备案号\n📦 共获取 {len(all_data)} 条产品数据\n📄 共获取 {len(all_patents)} 条专利数据\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
                return 'NEED_UPDATE_CAPTCHA', all_data, all_patents

            if count > 0:
                numbers_crawled += 1
                msg = f"备案号 {reg_num} 获取到 {count} 条产品数据，{len(all_patents) - prev_patents_count} 条专利数据\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
            else:
                msg = f"备案号 {reg_num} 没有找到数据\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())

            # 随机延迟1-3秒，避免请求过快
            time.sleep(random.uniform(1, 3))

        except requests.exceptions.RequestException as e:
            msg = f"请求备案号 {reg_num} 时出错: {e}\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())
            continue
        except json.JSONDecodeError as e:
            msg = f"解析备案号 {reg_num} 的JSON数据时出错: {e}\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())
            continue
        except Exception as e:
            msg = f"处理备案号 {reg_num} 数据时出错: {e}\n"
            if callback:
                callback(msg)
            else:
                print(msg.strip())
            continue

    msg = f"\n总共爬取 {len(all_data)} 条产品数据，{len(all_patents)} 条专利数据\n产品数据已保存到 {product_csv}\n专利数据已保存到 {patent_csv}\n"
    if callback:
        callback(msg)
    else:
        print(msg.strip())
    return None, all_data, all_patents


def read_registration_numbers_from_excel(file_path):
    """
    从Excel文件读取备案号（第二列）

    :param file_path: Excel文件路径
    :return: 备案号列表
    """
    try:
        df = pd.read_excel(file_path)
        # 获取第二列（索引为1）
        if len(df.columns) < 2:
            return []
        second_column = df.iloc[:, 1]  # 第二列
        # 转换为列表，去除空值
        reg_numbers = [str(x).strip() for x in second_column if pd.notna(x) and str(x).strip()]
        return reg_numbers
    except ImportError as e:
        error_msg = str(e)
        if 'openpyxl' in error_msg.lower():
            raise Exception(
                f"读取Excel文件失败: {error_msg}\n\n请安装或升级openpyxl到3.1.0或更高版本：\npip install --upgrade openpyxl>=3.1.0\n\n或查看 requirements.txt 和 安装说明.txt 文件获取详细安装说明")
        else:
            raise Exception(
                f"读取Excel文件失败: {error_msg}\n\n请确保已安装所需依赖：\npip install pandas openpyxl>=3.1.0")
    except Exception as e:
        error_msg = str(e)
        if 'openpyxl' in error_msg.lower() and 'version' in error_msg.lower():
            raise Exception(
                f"读取Excel文件失败: {error_msg}\n\n请升级openpyxl到3.1.0或更高版本：\npip install --upgrade openpyxl>=3.1.0\n\n或查看 requirements.txt 和 安装说明.txt 文件获取详细安装说明")
        else:
            raise Exception(f"读取Excel文件失败: {error_msg}")


def read_company_names_from_excel(file_path):
    """
    从Excel文件读取公司名称（第一列，无表头）

    :param file_path: Excel文件路径
    :return: 公司名称列表
    """
    try:
        df = pd.read_excel(file_path, header=None)
        if len(df.columns) < 1:
            return []
        first_column = df.iloc[:, 0]  # 第一列
        # 转换为列表，去除空值
        company_names = [str(x).strip() for x in first_column if pd.notna(x) and str(x).strip()]
        return company_names
    except ImportError as e:
        error_msg = str(e)
        if 'openpyxl' in error_msg.lower():
            raise Exception(
                f"读取Excel文件失败: {error_msg}\n\n请安装或升级openpyxl到3.1.0或更高版本：\npip install --upgrade openpyxl>=3.1.0")
        else:
            raise Exception(
                f"读取Excel文件失败: {error_msg}\n\n请确保已安装所需依赖：\npip install pandas openpyxl>=3.1.0")
    except Exception as e:
        error_msg = str(e)
        if 'openpyxl' in error_msg.lower() and 'version' in error_msg.lower():
            raise Exception(
                f"读取Excel文件失败: {error_msg}\n\n请升级openpyxl到3.1.0或更高版本：\npip install --upgrade openpyxl>=3.1.0")
        else:
            raise Exception(f"读取Excel文件失败: {error_msg}")


def crawl_by_company_names(company_names, captchaverification=None,
                           save_dir=None, max_numbers_per_captcha=1000, callback=None, stop_check=None,
                           request_counter=None, current_count=0, product_csv=None, patent_csv=None):
    """
    按公司名称爬取专利数据并保存到CSV文件
    与备案号不同的是，一个公司名称可能对应多个产品和专利，需要翻页获取全部数据

    :param company_names: 公司名称列表
    :param captchaverification: 验证码参数
    :param save_dir: 保存目录，None表示使用当前目录
    :param max_numbers_per_captcha: 每个验证码最多爬取的公司数量
    :param callback: 回调函数，用于更新GUI状态
    :param stop_check: 停止检查函数，返回True表示需要停止
    :param product_csv: 产品CSV文件路径（可选，如果提供则使用该文件）
    :param patent_csv: 专利CSV文件路径（可选，如果提供则使用该文件）
    :return: 返回所有爬取的数据列表，如果需要更新验证码返回'NEED_UPDATE_CAPTCHA'
    """
    # 确定保存目录
    if save_dir is None:
        save_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        os.makedirs(save_dir, exist_ok=True)

    # 如果没有提供文件名，则生成新的
    if product_csv is None or patent_csv is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        product_csv = os.path.join(save_dir, f'产品_按公司名称_{timestamp}.csv')
        patent_csv = os.path.join(save_dir, f'专利_按公司名称_{timestamp}.csv')

    if callback:
        callback(f"数据将保存到: {product_csv} 和 {patent_csv}\n")
        callback(f"共需要爬取 {len(company_names)} 个公司\n")
    else:
        print(f"数据将保存到: {product_csv} 和 {patent_csv}")
        print(f"共需要爬取 {len(company_names)} 个公司")

    url = "https://api.zlcp.org.cn/eszlcp/api/es/pro/page"

    # 请求头
    headers = get_headers(captchaverification)

    all_data = []
    all_patents = []
    companies_crawled = 0

    # 产品CSV表头：固定保留的中文表头（公司名称模式增加"查询公司"列）
    product_base_headers = ['查询公司', '产品名称', '产品备案号', '产品链接']

    # 专利CSV表头
    patent_base_headers = ['产品名称', '产品备案号', '产品链接', '认定年份']
    patent_field_headers = ['patTotal', 'num', 'name', 'type', 'isCore', 'isAuthShow', 'litigationNO', 'ad', 'apd',
                            'contribution']
    patent_headers = patent_base_headers + patent_field_headers

    # 初始化产品CSV文件
    product_file_initialized_ref = {'initialized': False, 'headers': None}

    # 检查专利CSV文件是否存在
    if os.path.exists(patent_csv):
        if callback:
            callback(f"将追加数据到 {patent_csv}\n")
        else:
            print(f"将追加数据到 {patent_csv}")
    else:
        if callback:
            callback(f"创建新文件: {patent_csv}\n")
        else:
            print(f"创建新文件: {patent_csv}")
        with open(patent_csv, 'w', newline='', encoding='gbk', errors='ignore') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=patent_headers)
            writer.writeheader()

    # 检查产品CSV文件是否存在
    if os.path.exists(product_csv):
        if callback:
            callback(f"将追加数据到 {product_csv}\n")
        else:
            print(f"将追加数据到 {product_csv}")
        try:
            with open(product_csv, 'r', encoding='gbk', errors='ignore') as csvfile:
                reader = csv.DictReader(csvfile)
                if reader.fieldnames:
                    product_file_initialized_ref['initialized'] = True
                    product_file_initialized_ref['headers'] = list(reader.fieldnames)
        except Exception as e:
            if callback:
                callback(f"读取产品CSV表头失败: {e}\n")
            else:
                print(f"读取产品CSV表头失败: {e}")
    else:
        if callback:
            callback(f"创建新文件: {product_csv}\n")
        else:
            print(f"创建新文件: {product_csv}")

    # 用于缓存没有查到数据的公司空记录，最后统一写入CSV（避免空记录抢先初始化表头导致字段丢失）
    empty_company_rows = []

    for idx, company_name in enumerate(company_names):
        # 检查是否需要停止
        if stop_check and stop_check():
            if callback:
                callback(f"\n⏹️ 用户停止爬取\n")
            return 'STOPPED', all_data, all_patents

        # 检查是否超过每个验证码的最大数量限制
        if companies_crawled >= max_numbers_per_captcha:
            if callback:
                callback(f"\n⚠️ 已达到每个验证码的最大公司数量限制 ({max_numbers_per_captcha} 个)\n")
            else:
                print(f"\n⚠️ 已达到每个验证码的最大公司数量限制 ({max_numbers_per_captcha} 个)")
            return 'NEED_UPDATE_CAPTCHA', all_data, all_patents

        # 清理公司名称
        company_name = str(company_name).strip()
        if not company_name:
            continue

        msg = f"\n{'=' * 50}\n正在爬取公司 {company_name} ({idx + 1}/{len(company_names)})...\n"
        if callback:
            callback(msg)
        else:
            print(msg.strip())

        # 公司名称可能对应多个产品，需要翻页获取全部
        page = 1
        company_product_count = 0
        company_patent_count = 0

        while True:
            # 检查是否需要停止
            if stop_check and stop_check():
                if callback:
                    callback(f"\n⏹️ 用户停止爬取\n")
                return 'STOPPED', all_data, all_patents

            # 请求体 - 使用公司名称作为查询条件
            payload = {
                "isPub": None,
                "limit": 10,
                "page": page,
                "query": company_name,
                "proSort": "Score",
                "queryRange": "All",
                "proUnspscCode": "",
                "queryDateBegin": None,
                "queryDateEnd": None,
                "queryDateType": 0,
                "areaCode": ""
            }

            try:
                msg = f"  正在获取第 {page} 页数据...\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())

                # 发送POST请求
                response = requests.post(url, headers=headers, json=payload, timeout=30)

                # 更新请求计数
                if request_counter:
                    current_count += 1
                    request_counter(current_count)

                # 检查响应状态
                response.raise_for_status()

                # 解析JSON响应
                json_data = response.json()

                # 检查是否有数据
                if json_data.get('code') != 0 or not json_data.get('data'):
                    # 检查是否是验证码问题
                    error_msg_text = json_data.get('message', '')
                    error_code = json_data.get('code')
                    if '验证' in error_msg_text or 'captcha' in error_msg_text.lower() or error_code in [401, 403]:
                        msg = f"\n❌ 验证码已失效！程序停止\n📊 已成功爬取 {idx} 个公司\n📦 共获取 {len(all_data)} 条产品数据\n📄 共获取 {len(all_patents)} 条专利数据\n"
                        if callback:
                            callback(msg)
                        else:
                            print(msg.strip())
                        return 'NEED_UPDATE_CAPTCHA', all_data, all_patents

                    if page == 1:
                        msg = f"  公司 {company_name} 没有找到数据，记录空行\n"
                        if callback:
                            callback(msg)
                        else:
                            print(msg.strip())
                        # 没有找到数据，先缓存空记录，最后统一写入CSV
                        empty_row = {'查询公司': company_name, '产品名称': '', '产品备案号': '', '产品链接': ''}
                        empty_company_rows.append(empty_row)
                        all_data.append(empty_row)
                    break

                # 获取总数信息
                data = json_data['data']
                total = data.get('total', 0)
                product_list = data.get('list', [])

                if page == 1:
                    msg = f"  公司 {company_name} 共找到 {total} 条产品记录\n"
                    if callback:
                        callback(msg)
                    else:
                        print(msg.strip())

                if not product_list:
                    if page == 1:
                        # 接口返回成功但列表为空，先缓存空记录，最后统一写入CSV
                        empty_row = {'查询公司': company_name, '产品名称': '', '产品备案号': '', '产品链接': ''}
                        empty_company_rows.append(empty_row)
                        all_data.append(empty_row)
                        msg = f"  公司 {company_name} 产品列表为空，记录空行\n"
                        if callback:
                            callback(msg)
                        else:
                            print(msg.strip())
                    break

                # 提取产品数据
                prev_data_count = len(all_data)
                prev_patents_count = len(all_patents)

                count = extract_product_data(
                    json_data, all_data, all_patents, headers,
                    need_detail=True,
                    product_csv=product_csv,
                    patent_csv=patent_csv,
                    product_headers=product_file_initialized_ref.get('headers'),
                    patent_headers=patent_headers,
                    product_base_headers=product_base_headers,
                    product_file_initialized_ref=product_file_initialized_ref,
                    callback=callback,
                    request_counter=request_counter,
                    current_count_ref=[current_count],
                    extra_fields={'查询公司': company_name}
                )

                # 检查是否需要更新验证码
                if count == 'NEED_UPDATE_CAPTCHA':
                    msg = f"\n❌ 验证码已失效！程序停止\n📊 已成功爬取 {idx} 个公司\n📦 共获取 {len(all_data)} 条产品数据\n📄 共获取 {len(all_patents)} 条专利数据\n"
                    if callback:
                        callback(msg)
                    else:
                        print(msg.strip())
                    return 'NEED_UPDATE_CAPTCHA', all_data, all_patents

                if count > 0:
                    company_product_count += count
                    company_patent_count += len(all_patents) - prev_patents_count
                    msg = f"  第 {page} 页获取到 {count} 条产品数据，{len(all_patents) - prev_patents_count} 条专利数据\n"
                    if callback:
                        callback(msg)
                    else:
                        print(msg.strip())
                else:
                    break

                # 检查是否还有下一页
                total_pages = (total + 9) // 10  # 每页10条，向上取整
                if page >= total_pages:
                    break

                page += 1
                # 随机延迟1-3秒，避免请求过快
                time.sleep(random.uniform(1, 3))

            except requests.exceptions.RequestException as e:
                msg = f"  请求公司 {company_name} 第 {page} 页时出错: {e}\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
                break
            except json.JSONDecodeError as e:
                msg = f"  解析公司 {company_name} 第 {page} 页的JSON数据时出错: {e}\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
                break
            except Exception as e:
                msg = f"  处理公司 {company_name} 第 {page} 页数据时出错: {e}\n"
                if callback:
                    callback(msg)
                else:
                    print(msg.strip())
                break

        companies_crawled += 1
        msg = f"  ✅ 公司 {company_name} 完成，获取 {company_product_count} 条产品，{company_patent_count} 条专利\n"
        if callback:
            callback(msg)
        else:
            print(msg.strip())

        # 随机延迟1-3秒，避免请求过快
        time.sleep(random.uniform(1, 3))

    # 最后统一写入没有查到数据的公司空记录到产品CSV
    if empty_company_rows and product_csv:
        if callback:
            callback(f"\n📝 正在写入 {len(empty_company_rows)} 条无数据公司的空记录...\n")

        if product_file_initialized_ref and product_file_initialized_ref.get('initialized', False):
            # CSV已经被有数据的公司正确初始化了（含完整表头），直接追加空记录
            current_headers = product_file_initialized_ref.get('headers', [])
            if current_headers:
                try:
                    with open(product_csv, 'a', newline='', encoding='gbk', errors='ignore') as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=current_headers)
                        for empty_row in empty_company_rows:
                            clean_row = {k: str(empty_row.get(k, '')) for k in current_headers}
                            writer.writerow(clean_row)
                except Exception as e:
                    print(f"    写入空记录到产品CSV失败: {e}")
        else:
            # 所有公司都没有数据，用基础表头初始化CSV并写入空记录
            try:
                with open(product_csv, 'w', newline='', encoding='gbk', errors='ignore') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=product_base_headers)
                    writer.writeheader()
                    for empty_row in empty_company_rows:
                        clean_row = {k: str(empty_row.get(k, '')) for k in product_base_headers}
                        writer.writerow(clean_row)
                product_file_initialized_ref['initialized'] = True
                product_file_initialized_ref['headers'] = product_base_headers
            except Exception as e:
                print(f"    初始化并写入空记录到产品CSV失败: {e}")

    msg = f"\n总共爬取 {len(all_data)} 条产品数据（含 {len(empty_company_rows)} 条无数据公司），{len(all_patents)} 条专利数据\n产品数据已保存到 {product_csv}\n专利数据已保存到 {patent_csv}\n"
    if callback:
        callback(msg)
    else:
        print(msg.strip())
    return None, all_data, all_patents


class CrawlerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("专利数据爬取工具")
        self.root.geometry("1400x700")  # 扩大窗口

        # 设置样式
        self.setup_styles()

        # 变量
        self.crawl_mode = tk.StringVar(value="page")
        self.captchaverification = tk.StringVar()
        # 使用getcwd()获取当前工作目录，打包后更可靠
        self.save_dir = tk.StringVar(value=os.getcwd())
        self.max_requests_per_captcha = tk.IntVar(value=1000)
        self.current_request_count = tk.IntVar(value=0)

        # 页数爬取相关变量
        self.start_page = tk.IntVar(value=1)
        self.end_page = tk.IntVar(value=1)
        self.page_limit = tk.IntVar(value=50)  # 每页数量，默认50

        # 备案号爬取相关变量
        self.registration_numbers = []
        self.export_split_count = tk.IntVar(value=150)  # 导出时每多少个备案号添加分割线

        # 公司名称爬取相关变量
        self.company_names = []
        self.company_export_split_count = tk.IntVar(value=150)  # 导出时每多少个公司名称添加分割线

        # 爬取状态
        self.is_crawling = False
        self.should_stop = False  # 用户主动停止标志

        # 用于线程间通信的变量
        self.new_captcha_result = None
        self.captcha_dialog_event = threading.Event()

        self.create_widgets()

    def setup_styles(self):
        """设置界面样式"""
        style = ttk.Style()

        # 使用clam主题作为基础（更现代的外观）
        style.theme_use('clam')

        # 定义颜色
        bg_color = '#f0f4f8'  # 浅蓝灰背景
        frame_bg = '#e8eef5'  # 框架背景
        accent_color = '#4a90d9'  # 主色调蓝色
        accent_hover = '#3a7bc8'  # 悬停蓝色
        success_color = '#28a745'  # 绿色（开始按钮）
        success_hover = '#218838'
        danger_color = '#dc3545'  # 红色（停止按钮）
        danger_hover = '#c82333'
        text_color = '#2c3e50'  # 深色文字

        # 设置根窗口背景
        self.root.configure(bg=bg_color)

        # 配置Frame样式
        style.configure('TFrame', background=bg_color)
        style.configure('TLabelframe', background=frame_bg, bordercolor=accent_color)
        style.configure('TLabelframe.Label', background=frame_bg, foreground=accent_color,
                        font=('Microsoft YaHei UI', 10, 'bold'))

        # 配置Label样式
        style.configure('TLabel', background=frame_bg, foreground=text_color,
                        font=('Microsoft YaHei UI', 9))

        # 配置Entry样式
        style.configure('TEntry', fieldbackground='white', foreground=text_color)

        # 配置Spinbox样式
        style.configure('TSpinbox', fieldbackground='white', foreground=text_color)

        # 配置Radiobutton样式
        style.configure('TRadiobutton', background=frame_bg, foreground=text_color,
                        font=('Microsoft YaHei UI', 9))

        # 配置普通按钮样式
        style.configure('TButton',
                        background=accent_color,
                        foreground='white',
                        font=('Microsoft YaHei UI', 9, 'bold'),
                        padding=(10, 5))
        style.map('TButton',
                  background=[('active', accent_hover), ('pressed', accent_hover)])

        # 配置开始按钮样式（绿色）
        style.configure('Start.TButton',
                        background=success_color,
                        foreground='white',
                        font=('Microsoft YaHei UI', 10, 'bold'),
                        padding=(15, 8))
        style.map('Start.TButton',
                  background=[('active', success_hover), ('pressed', success_hover)])

        # 配置停止按钮样式（红色）
        style.configure('Stop.TButton',
                        background=danger_color,
                        foreground='white',
                        font=('Microsoft YaHei UI', 10, 'bold'),
                        padding=(15, 8))
        style.map('Stop.TButton',
                  background=[('active', danger_hover), ('pressed', danger_hover)])

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)  # 左侧日志区域
        main_frame.columnconfigure(1, weight=0)  # 中间设置区域
        main_frame.columnconfigure(2, weight=0)  # 右侧备案号列表区域
        main_frame.rowconfigure(0, weight=1)

        # ========== 左侧：日志区域 ==========
        left_frame = ttk.Frame(main_frame)
        left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(1, weight=1)

        # 验证码输入（放在左侧顶部）
        captcha_frame = ttk.LabelFrame(left_frame, text="验证码参数", padding="5")
        captcha_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        captcha_frame.columnconfigure(0, weight=1)

        # 验证码获取说明
        help_frame = ttk.Frame(captcha_frame)
        help_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        help_frame.columnconfigure(1, weight=1)

        ttk.Label(help_frame, text="验证码获取：", font=("", 11)).grid(row=0, column=0, sticky=tk.W)

        # 创建说明文字和链接
        help_text_frame = ttk.Frame(help_frame)
        help_text_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=2)

        help_text = "打开 "
        ttk.Label(help_text_frame, text=help_text, font=("", 10)).pack(side=tk.LEFT)

        # 可点击的链接
        link_url = "https://www.zlcp.org.cn/search/2c8b39fb-dd8a-4485-aae4-8aa8eaad9410?y=2025&isPub"
        link_label = tk.Label(help_text_frame, text=link_url, fg="blue", cursor="hand2", font=("", 10, "underline"))
        link_label.pack(side=tk.LEFT)
        link_label.bind("<Button-1>", lambda e: webbrowser.open(link_url))

        # 详细说明
        detail_text = "按F12或右键检查 → 选择网络 → 选择Fetch/XHR → 手动验证码 → 点击detail → 获取captchaverification的值"
        detail_label = ttk.Label(help_frame, text=detail_text, font=("", 10), foreground="black", wraplength=500)
        detail_label.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(2, 5))

        # 验证码输入框
        ttk.Label(captcha_frame, text="验证码参数（自动获取）超过5次后用户手动获取：", font=("", 11)).grid(row=1, column=0, sticky=tk.W, padx=5,
                                                                         pady=(5, 2))
        ttk.Entry(captcha_frame, textvariable=self.captchaverification).grid(row=2, column=0, sticky=(tk.W, tk.E),
                                                                             padx=5, pady=(0, 5))

        # 日志输出
        log_frame = ttk.LabelFrame(left_frame, text="运行日志", padding="5")
        log_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, width=60,
                                                  font=('Consolas', 9),
                                                  bg='#ffffff',
                                                  fg='#2c3e50',
                                                  insertbackground='#4a90d9',
                                                  selectbackground='#4a90d9',
                                                  selectforeground='white',
                                                  relief='flat',
                                                  borderwidth=1)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 控制按钮（放在日志下方）
        button_frame = ttk.Frame(left_frame)
        button_frame.grid(row=2, column=0, pady=10)

        self.start_button = ttk.Button(button_frame, text="🚀 开始爬取", command=self.start_crawl, style='Start.TButton')
        self.start_button.pack(side=tk.LEFT, padx=10)

        self.stop_button = ttk.Button(button_frame, text="⏹ 停止", command=self.stop_crawl, state=tk.DISABLED,
                                      style='Stop.TButton')
        self.stop_button.pack(side=tk.LEFT, padx=10)

        # ========== 中间：设置区域 ==========
        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=0, column=1, sticky=(tk.N, tk.S), padx=(0, 10))

        row = 0

        # 保存路径选择
        path_frame = ttk.LabelFrame(right_frame, text="保存路径", padding="8")
        path_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=5)
        path_frame.columnconfigure(0, weight=1)

        ttk.Entry(path_frame, textvariable=self.save_dir, width=40).grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5,
                                                                         pady=3)
        ttk.Button(path_frame, text="选择目录", command=self.select_save_dir).grid(row=1, column=0, pady=3)
        row += 1

        # 验证码更换频次设置
        limit_frame = ttk.LabelFrame(right_frame, text="验证码更换频次", padding="8")
        limit_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=5)
        limit_frame.columnconfigure(1, weight=1)

        ttk.Label(limit_frame, text="请求次数限制:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.max_requests_spinbox = ttk.Spinbox(limit_frame, from_=1, to=100000,
                                                textvariable=self.max_requests_per_captcha, width=12, state='disabled')
        self.max_requests_spinbox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=3)

        # 保存和修改按钮
        button_frame = ttk.Frame(limit_frame)
        button_frame.grid(row=0, column=2, sticky=tk.W, padx=5, pady=3)

        self.save_limit_btn = ttk.Button(button_frame, text="保存", command=self.save_request_limit, width=6)
        self.save_limit_btn.pack(side=tk.LEFT, padx=2)
        self.save_limit_btn.config(state='disabled')  # 初始状态禁用

        self.edit_limit_btn = ttk.Button(button_frame, text="修改", command=self.edit_request_limit, width=6)
        self.edit_limit_btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(limit_frame, text="当前请求次数:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        self.request_count_label = ttk.Label(limit_frame, text="0", font=('Microsoft YaHei UI', 10, 'bold'),
                                             foreground='#4a90d9')
        self.request_count_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=3)
        row += 1

        # 爬取方式选择（放在同一行）
        mode_frame = ttk.LabelFrame(right_frame, text="爬取方式", padding="8")
        mode_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=5)

        ttk.Radiobutton(mode_frame, text="按页数爬取", variable=self.crawl_mode, value="page",
                        command=self.on_mode_change).pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Radiobutton(mode_frame, text="按备案号爬取", variable=self.crawl_mode, value="reg",
                        command=self.on_mode_change).pack(side=tk.LEFT, padx=10, pady=2)
        ttk.Radiobutton(mode_frame, text="按公司名称爬取", variable=self.crawl_mode, value="company",
                        command=self.on_mode_change).pack(side=tk.LEFT, padx=10, pady=2)
        row += 1

        # 页数爬取设置
        self.page_frame = ttk.LabelFrame(right_frame, text="页数爬取设置", padding="8")
        self.page_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(self.page_frame, text="起始页码:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=8)
        ttk.Spinbox(self.page_frame, from_=1, to=100000, textvariable=self.start_page, width=12).grid(row=0, column=1,
                                                                                                      sticky=tk.W,
                                                                                                      padx=5, pady=8)

        ttk.Label(self.page_frame, text="结束页码:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=8)
        ttk.Spinbox(self.page_frame, from_=1, to=100000, textvariable=self.end_page, width=12).grid(row=1, column=1,
                                                                                                    sticky=tk.W, padx=5,
                                                                                                    pady=8)

        ttk.Label(self.page_frame, text="每页数量:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=8)
        ttk.Spinbox(self.page_frame, from_=1, to=100, textvariable=self.page_limit, width=12).grid(row=2, column=1,
                                                                                                   sticky=tk.W, padx=5,
                                                                                                   pady=8)
        row += 1

        # 备案号爬取设置
        self.reg_frame = ttk.LabelFrame(right_frame, text="备案号爬取设置", padding="8")
        self.reg_frame.grid(row=row, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.reg_frame.columnconfigure(1, weight=1)
        right_frame.rowconfigure(row, weight=1)

        # 批量粘贴备案号
        ttk.Label(self.reg_frame, text="批量粘贴:").grid(row=0, column=0, sticky=(tk.W, tk.N), padx=5, pady=(5, 8))
        paste_frame = ttk.Frame(self.reg_frame)
        paste_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=(5, 8))
        paste_frame.columnconfigure(0, weight=1)
        paste_frame.rowconfigure(0, weight=1)

        # 多行文本框用于粘贴备案号
        self.paste_text = scrolledtext.ScrolledText(paste_frame, height=5, width=30,
                                                    font=('Microsoft YaHei UI', 9),
                                                    wrap=tk.WORD)
        self.paste_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 3))

        # 按钮框架
        paste_btn_frame = ttk.Frame(paste_frame)
        paste_btn_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        ttk.Button(paste_btn_frame, text="导入", command=self.import_from_paste, width=8).pack(side=tk.LEFT,
                                                                                               padx=(0, 5))
        ttk.Button(paste_btn_frame, text="清空", command=self.clear_paste_text, width=8).pack(side=tk.LEFT)

        # 导入Excel文件
        ttk.Label(self.reg_frame, text="导入Excel:",
                  font=('Microsoft YaHei UI', 10, 'bold')).grid(row=1, column=0, sticky=(tk.W, tk.N), padx=5,
                                                                pady=(8, 8), rowspan=2)
        excel_frame = ttk.Frame(self.reg_frame)
        excel_frame.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(8, 8), rowspan=2)
        excel_frame.columnconfigure(0, weight=1)
        self.excel_path_var = tk.StringVar()
        ttk.Entry(excel_frame, textvariable=self.excel_path_var, width=28).grid(row=0, column=0, columnspan=2,
                                                                                sticky=(tk.W, tk.E), pady=(0, 5))
        ttk.Button(excel_frame, text="选择文件", command=self.select_excel_file, width=8).grid(row=1, column=0,
                                                                                               sticky=tk.W)
        ttk.Button(excel_frame, text="解析", command=self.parse_excel_file, width=8).grid(row=1, column=1, sticky=tk.E)

        # 导出设置
        ttk.Label(self.reg_frame, text="导出设置:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=(8, 5))
        export_frame = ttk.Frame(self.reg_frame)
        export_frame.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=5, pady=(8, 5))

        ttk.Label(export_frame, text="每").pack(side=tk.LEFT, padx=(0, 2))
        ttk.Spinbox(export_frame, from_=1, to=1000, textvariable=self.export_split_count, width=6).pack(side=tk.LEFT,
                                                                                                        padx=2)
        ttk.Label(export_frame, text="个分割").pack(side=tk.LEFT, padx=(2, 5))
        ttk.Button(export_frame, text="导出TXT", command=self.export_reg_numbers_to_txt, width=7).pack(side=tk.LEFT,
                                                                                                       padx=2)
        ttk.Button(export_frame, text="导出表格", command=self.export_reg_numbers_to_excel, width=7).pack(side=tk.LEFT,
                                                                                                          padx=2)

        # 公司名称爬取设置
        self.company_frame = ttk.LabelFrame(right_frame, text="公司名称爬取设置", padding="8")
        self.company_frame.grid(row=row, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.company_frame.columnconfigure(1, weight=1)
        right_frame.rowconfigure(row, weight=1)

        # 批量粘贴公司名称
        ttk.Label(self.company_frame, text="批量粘贴:").grid(row=0, column=0, sticky=(tk.W, tk.N), padx=5, pady=(5, 8))
        company_paste_frame = ttk.Frame(self.company_frame)
        company_paste_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=(5, 8))
        company_paste_frame.columnconfigure(0, weight=1)
        company_paste_frame.rowconfigure(0, weight=1)

        # 多行文本框用于粘贴公司名称
        self.company_paste_text = scrolledtext.ScrolledText(company_paste_frame, height=5, width=30,
                                                            font=('Microsoft YaHei UI', 9),
                                                            wrap=tk.WORD)
        self.company_paste_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 3))

        # 按钮框架
        company_paste_btn_frame = ttk.Frame(company_paste_frame)
        company_paste_btn_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        ttk.Button(company_paste_btn_frame, text="导入", command=self.import_company_from_paste, width=8).pack(
            side=tk.LEFT, padx=(0, 5))
        ttk.Button(company_paste_btn_frame, text="清空", command=self.clear_company_paste_text, width=8).pack(
            side=tk.LEFT)

        # 导入Excel文件（公司名称）
        ttk.Label(self.company_frame, text="导入Excel:",
                  font=('Microsoft YaHei UI', 10, 'bold')).grid(row=1, column=0, sticky=(tk.W, tk.N), padx=5,
                                                                pady=(8, 8), rowspan=2)
        company_excel_frame = ttk.Frame(self.company_frame)
        company_excel_frame.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(8, 8), rowspan=2)
        company_excel_frame.columnconfigure(0, weight=1)
        self.company_excel_path_var = tk.StringVar()
        ttk.Entry(company_excel_frame, textvariable=self.company_excel_path_var, width=28).grid(row=0, column=0,
                                                                                                columnspan=2,
                                                                                                sticky=(tk.W, tk.E),
                                                                                                pady=(0, 5))
        ttk.Button(company_excel_frame, text="选择文件", command=self.select_company_excel_file, width=8).grid(row=1,
                                                                                                               column=0,
                                                                                                               sticky=tk.W)
        ttk.Button(company_excel_frame, text="解析", command=self.parse_company_excel_file, width=8).grid(row=1,
                                                                                                          column=1,
                                                                                                          sticky=tk.E)

        # 导出设置（公司名称）
        ttk.Label(self.company_frame, text="导出设置:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=(8, 5))
        company_export_frame = ttk.Frame(self.company_frame)
        company_export_frame.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=5, pady=(8, 5))

        ttk.Label(company_export_frame, text="每").pack(side=tk.LEFT, padx=(0, 2))
        ttk.Spinbox(company_export_frame, from_=1, to=1000, textvariable=self.company_export_split_count, width=6).pack(
            side=tk.LEFT, padx=2)
        ttk.Label(company_export_frame, text="个分割").pack(side=tk.LEFT, padx=(2, 5))
        ttk.Button(company_export_frame, text="导出TXT", command=self.export_company_names_to_txt, width=7).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(company_export_frame, text="导出表格", command=self.export_company_names_to_excel, width=7).pack(
            side=tk.LEFT, padx=2)

        row += 1

        # ========== 最右侧：备案号列表区域 ==========
        list_outer_frame = ttk.Frame(main_frame)
        list_outer_frame.grid(row=0, column=2, sticky=(tk.N, tk.S, tk.E, tk.W), padx=(0, 0))
        list_outer_frame.columnconfigure(0, weight=1)
        list_outer_frame.rowconfigure(0, weight=1)

        # 数据列表显示（备案号/公司名称共用）
        self.list_label_frame = ttk.LabelFrame(list_outer_frame, text="备案号列表", padding="8")
        self.list_label_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.list_label_frame.columnconfigure(0, weight=1)
        self.list_label_frame.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(self.list_label_frame)
        list_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.reg_listbox = tk.Listbox(list_frame, height=30, width=35,
                                      font=('Microsoft YaHei UI', 9),
                                      bg='white',
                                      fg='#2c3e50',
                                      selectbackground='#4a90d9',
                                      selectforeground='white',
                                      relief='flat',
                                      borderwidth=1)
        self.reg_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.reg_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.reg_listbox.config(yscrollcommand=scrollbar.set)

        # 清空列表按钮
        ttk.Button(self.list_label_frame, text="清空列表", command=self.clear_current_list, width=12).grid(row=1,
                                                                                                           column=0,
                                                                                                           pady=(5, 0))

        # 初始显示页数爬取设置
        self.on_mode_change()

    def on_mode_change(self):
        """切换爬取方式时更新界面"""
        mode = self.crawl_mode.get()
        if mode == "page":
            self.page_frame.grid()
            self.reg_frame.grid_remove()
            self.company_frame.grid_remove()
            self.list_label_frame.config(text="备案号列表")
            self.update_reg_listbox()
        elif mode == "reg":
            self.page_frame.grid_remove()
            self.reg_frame.grid()
            self.company_frame.grid_remove()
            self.list_label_frame.config(text="备案号列表")
            self.update_reg_listbox()
        elif mode == "company":
            self.page_frame.grid_remove()
            self.reg_frame.grid_remove()
            self.company_frame.grid()
            self.list_label_frame.config(text="公司名称列表")
            self.update_company_listbox()

    def save_request_limit(self):
        """保存请求次数限制"""
        self.max_requests_spinbox.config(state='disabled')
        self.save_limit_btn.config(state='disabled')
        self.edit_limit_btn.config(state='normal')
        messagebox.showinfo("提示", f"请求次数限制已保存为: {self.max_requests_per_captcha.get()}")

    def edit_request_limit(self):
        """修改请求次数限制"""
        self.max_requests_spinbox.config(state='normal')
        self.save_limit_btn.config(state='normal')
        self.edit_limit_btn.config(state='disabled')

    def select_save_dir(self):
        """选择保存目录"""
        dir_path = filedialog.askdirectory(initialdir=self.save_dir.get())
        if dir_path:
            self.save_dir.set(dir_path)

    def select_excel_file(self):
        """选择Excel文件"""
        file_path = filedialog.askopenfilename(
            title="选择Excel文件",
            filetypes=[("Excel文件", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        if file_path:
            self.excel_path_var.set(file_path)

    def select_excel_file(self):
        """选择Excel文件"""
        file_path = filedialog.askopenfilename(
            title="选择Excel文件",
            filetypes=[("Excel文件", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        if file_path:
            self.excel_path_var.set(file_path)

    def parse_excel_file(self):
        """解析Excel文件，提取备案号"""
        file_path = self.excel_path_var.get()
        if not file_path:
            messagebox.showwarning("警告", "请先选择Excel文件")
            return

        if not os.path.exists(file_path):
            messagebox.showerror("错误", "文件不存在")
            return

        try:
            reg_numbers = read_registration_numbers_from_excel(file_path)
            if not reg_numbers:
                messagebox.showwarning("警告", "未能从Excel文件中读取到备案号")
                return

            # 添加到列表
            self.registration_numbers.extend(reg_numbers)
            self.update_reg_listbox()
            self.log(f"成功解析Excel文件，读取到 {len(reg_numbers)} 个备案号\n")
            messagebox.showinfo("成功", f"成功读取 {len(reg_numbers)} 个备案号")
        except Exception as e:
            messagebox.showerror("错误", f"解析Excel文件失败: {e}")
            self.log(f"解析Excel文件失败: {e}\n")

    def import_from_paste(self):
        """从粘贴文本框导入备案号"""
        text_content = self.paste_text.get("1.0", tk.END).strip()

        if not text_content:
            messagebox.showwarning("警告", "请先粘贴备案号")
            return

        try:
            reg_numbers = []
            lines = text_content.split('\n')

            for line in lines:
                line = line.strip()
                # 跳过空行、分割线、标题行等
                if not line:
                    continue
                if line.startswith('=') or line.startswith('-'):
                    continue
                if '备案号列表' in line or '导出时间' in line or '总数量' in line or '分割设置' in line:
                    continue

                # 支持多种分隔符：空格、逗号、分号、制表符
                # 先尝试按分隔符拆分
                parts = []
                for sep in ['\t', ',', ';', ' ']:
                    if sep in line:
                        parts = [p.strip() for p in line.split(sep) if p.strip()]
                        break

                if parts:
                    # 有分隔符，添加所有部分
                    for part in parts:
                        if part and part not in self.registration_numbers:
                            reg_numbers.append(part)
                else:
                    # 没有分隔符，整行作为一个备案号
                    if line and line not in self.registration_numbers:
                        reg_numbers.append(line)

            if not reg_numbers:
                messagebox.showwarning("警告", "未能从粘贴内容中读取到新的备案号")
                return

            # 添加到列表
            self.registration_numbers.extend(reg_numbers)
            self.update_reg_listbox()
            self.log(f"成功从粘贴内容导入 {len(reg_numbers)} 个备案号\n")
            messagebox.showinfo("成功", f"成功导入 {len(reg_numbers)} 个备案号")

            # 清空文本框
            self.paste_text.delete("1.0", tk.END)
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {e}")
            self.log(f"导入失败: {e}\n")

    def clear_paste_text(self):
        """清空粘贴文本框"""
        self.paste_text.delete("1.0", tk.END)

    def clear_reg_list(self):
        """清空备案号列表"""
        if messagebox.askyesno("确认", "确定要清空备案号列表吗？"):
            self.registration_numbers.clear()
            self.update_reg_listbox()
            self.log("已清空备案号列表\n")

    def clear_current_list(self):
        """清空当前模式的列表"""
        mode = self.crawl_mode.get()
        if mode == "company":
            self.clear_company_list()
        else:
            self.clear_reg_list()

    def select_company_excel_file(self):
        """选择公司名称Excel文件"""
        file_path = filedialog.askopenfilename(
            title="选择公司名称Excel文件",
            filetypes=[("Excel文件", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        if file_path:
            self.company_excel_path_var.set(file_path)

    def parse_company_excel_file(self):
        """解析Excel文件，提取公司名称"""
        file_path = self.company_excel_path_var.get()
        if not file_path:
            messagebox.showwarning("警告", "请先选择Excel文件")
            return

        if not os.path.exists(file_path):
            messagebox.showerror("错误", "文件不存在")
            return

        try:
            names = read_company_names_from_excel(file_path)
            if not names:
                messagebox.showwarning("警告", "未能从Excel文件中读取到公司名称")
                return

            # 添加到列表
            self.company_names.extend(names)
            self.update_company_listbox()
            self.log(f"成功解析Excel文件，读取到 {len(names)} 个公司名称\n")
            messagebox.showinfo("成功", f"成功读取 {len(names)} 个公司名称")
        except Exception as e:
            messagebox.showerror("错误", f"解析Excel文件失败: {e}")
            self.log(f"解析Excel文件失败: {e}\n")

    def import_company_from_paste(self):
        """从粘贴文本框导入公司名称"""
        text_content = self.company_paste_text.get("1.0", tk.END).strip()

        if not text_content:
            messagebox.showwarning("警告", "请先粘贴公司名称")
            return

        try:
            names = []
            lines = text_content.split('\n')

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('=') or line.startswith('-'):
                    continue
                if '公司名称列表' in line or '导出时间' in line or '总数量' in line or '分割设置' in line:
                    continue

                if line and line not in self.company_names:
                    names.append(line)

            if not names:
                messagebox.showwarning("警告", "未能从粘贴内容中读取到新的公司名称")
                return

            # 添加到列表
            self.company_names.extend(names)
            self.update_company_listbox()
            self.log(f"成功从粘贴内容导入 {len(names)} 个公司名称\n")
            messagebox.showinfo("成功", f"成功导入 {len(names)} 个公司名称")

            # 清空文本框
            self.company_paste_text.delete("1.0", tk.END)
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {e}")
            self.log(f"导入失败: {e}\n")

    def clear_company_paste_text(self):
        """清空公司名称粘贴文本框"""
        self.company_paste_text.delete("1.0", tk.END)

    def clear_company_list(self):
        """清空公司名称列表"""
        if messagebox.askyesno("确认", "确定要清空公司名称列表吗？"):
            self.company_names.clear()
            self.update_company_listbox()
            self.log("已清空公司名称列表\n")

    def update_company_listbox(self):
        """更新公司名称列表显示"""
        self.reg_listbox.delete(0, tk.END)
        for name in self.company_names:
            self.reg_listbox.insert(tk.END, name)

    def export_company_names_to_txt(self):
        """导出公司名称到TXT文件"""
        if not self.company_names:
            messagebox.showwarning("警告", "公司名称列表为空，无法导出")
            return

        # 选择保存文件
        file_path = filedialog.asksaveasfilename(
            title="导出公司名称",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=self.save_dir.get(),
            initialfile=f"公司名称列表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )

        if not file_path:
            return

        try:
            split_count = self.company_export_split_count.get()
            total_count = len(self.company_names)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"公司名称列表\n")
                f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总数量: {total_count}\n")
                f.write(f"分割设置: 每 {split_count} 个\n")
                f.write("=" * 50 + "\n\n")

                for idx, name in enumerate(self.company_names, 1):
                    # 每split_count个添加分割线
                    if idx > 1 and (idx - 1) % split_count == 0:
                        section_num = (idx - 1) // split_count
                        f.write(f"\n{'-' * 20} {section_num} {'-' * 20}\n\n")

                    f.write(f"{name}\n")

                # 最后一个分割线
                if total_count > split_count:
                    final_section = (total_count - 1) // split_count + 1
                    if total_count % split_count != 0 or total_count == split_count:
                        f.write(f"\n{'-' * 20} {final_section} {'-' * 20}\n")

            self.log(f"✅ 成功导出 {total_count} 个公司名称到: {file_path}\n")
            messagebox.showinfo("成功", f"成功导出 {total_count} 个公司名称")
        except Exception as e:
            self.log(f"❌ 导出失败: {e}\n")
            messagebox.showerror("错误", f"导出失败: {e}")

    def export_reg_numbers_to_txt(self):
        """导出备案号到TXT文件"""
        if not self.registration_numbers:
            messagebox.showwarning("警告", "备案号列表为空，无法导出")
            return

        # 选择保存文件
        file_path = filedialog.asksaveasfilename(
            title="导出备案号",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=self.save_dir.get(),
            initialfile=f"备案号列表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )

        if not file_path:
            return

        try:
            split_count = self.export_split_count.get()
            total_count = len(self.registration_numbers)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"备案号列表\n")
                f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总数量: {total_count}\n")
                f.write(f"分割设置: 每 {split_count} 个\n")
                f.write("=" * 50 + "\n\n")

                for idx, reg_num in enumerate(self.registration_numbers, 1):
                    # 每split_count个添加分割线
                    if idx > 1 and (idx - 1) % split_count == 0:
                        section_num = (idx - 1) // split_count
                        f.write(f"\n{'-' * 20} {section_num} {'-' * 20}\n\n")

                    f.write(f"{reg_num}\n")

                # 最后一个分割线
                if total_count > split_count:
                    final_section = (total_count - 1) // split_count + 1
                    if total_count % split_count != 0 or total_count == split_count:
                        f.write(f"\n{'-' * 20} {final_section} {'-' * 20}\n")

            self.log(f"✅ 成功导出 {total_count} 个备案号到: {file_path}\n")
            messagebox.showinfo("成功", f"成功导出 {total_count} 个备案号")
        except Exception as e:
            self.log(f"❌ 导出失败: {e}\n")
            messagebox.showerror("错误", f"导出失败: {e}")

    def export_reg_numbers_to_excel(self):
        """根据分割设置导出备案号到多个Excel文件"""
        if not self.registration_numbers:
            messagebox.showwarning("警告", "备案号列表为空，无法导出")
            return

        # 选择保存目录
        save_dir = filedialog.askdirectory(
            title="选择导出目录",
            initialdir=self.save_dir.get()
        )
        if not save_dir:
            return

        try:
            split_count = self.export_split_count.get()
            total_count = len(self.registration_numbers)
            # 按split_count横向切割
            chunks = [self.registration_numbers[i:i + split_count]
                      for i in range(0, total_count, split_count)]
            total_files = len(chunks)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            for file_idx, chunk in enumerate(chunks, 1):
                df = pd.DataFrame(chunk, columns=["备案号"])
                file_name = f"备案号列表_{file_idx}_{timestamp}.xlsx"
                file_path = os.path.join(save_dir, file_name)
                df.to_excel(file_path, index=False, engine='openpyxl')

            self.log(f"✅ 成功导出 {total_count} 个备案号，共 {total_files} 个Excel文件到: {save_dir}\n")
            messagebox.showinfo("成功", f"成功导出 {total_count} 个备案号\n共 {total_files} 个文件")
        except Exception as e:
            self.log(f"❌ 导出表格失败: {e}\n")
            messagebox.showerror("错误", f"导出表格失败: {e}")

    def export_company_names_to_excel(self):
        """根据分割设置导出公司名称到多个Excel文件"""
        if not self.company_names:
            messagebox.showwarning("警告", "公司名称列表为空，无法导出")
            return

        # 选择保存目录
        save_dir = filedialog.askdirectory(
            title="选择导出目录",
            initialdir=self.save_dir.get()
        )
        if not save_dir:
            return

        try:
            split_count = self.company_export_split_count.get()
            total_count = len(self.company_names)
            # 按split_count横向切割
            chunks = [self.company_names[i:i + split_count]
                      for i in range(0, total_count, split_count)]
            total_files = len(chunks)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            for file_idx, chunk in enumerate(chunks, 1):
                df = pd.DataFrame(chunk, columns=["公司名称"])
                file_name = f"公司名称列表_{file_idx}_{timestamp}.xlsx"
                file_path = os.path.join(save_dir, file_name)
                df.to_excel(file_path, index=False, engine='openpyxl')

            self.log(f"✅ 成功导出 {total_count} 个公司名称，共 {total_files} 个Excel文件到: {save_dir}\n")
            messagebox.showinfo("成功", f"成功导出 {total_count} 个公司名称\n共 {total_files} 个文件")
        except Exception as e:
            self.log(f"❌ 导出表格失败: {e}\n")
            messagebox.showerror("错误", f"导出表格失败: {e}")

    def update_reg_listbox(self):
        """更新备案号列表显示"""
        self.reg_listbox.delete(0, tk.END)
        for reg_num in self.registration_numbers:
            self.reg_listbox.insert(tk.END, reg_num)

    def update_request_count(self, count):
        """更新请求计数显示"""
        self.current_request_count.set(count)
        self.request_count_label.config(text=str(count))
        self.root.update_idletasks()

    def reset_request_count(self):
        """重置请求计数"""
        self.update_request_count(0)

    def log(self, message):
        """添加日志"""
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def start_crawl(self):
        """开始爬取"""
        if self.is_crawling:
            return

        mode = self.crawl_mode.get()
        if mode == "page":
            if self.start_page.get() > self.end_page.get():
                messagebox.showerror("错误", "起始页码不能大于结束页码")
                return
        elif mode == "reg":
            if not self.registration_numbers:
                messagebox.showerror("错误", "请添加至少一个备案号")
                return
        elif mode == "company":
            if not self.company_names:
                messagebox.showerror("错误", "请添加至少一个公司名称")
                return

        # 重置请求计数
        self.reset_request_count()

        # 更新界面状态
        self.is_crawling = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)

        # 在新线程中执行爬取
        thread = threading.Thread(target=self.crawl_thread, daemon=True)
        thread.start()

    def auto_refresh_captcha(self, reason=""):
        """
        自动刷新验证码：先尝试自动破解，失败后弹窗让用户手动输入
        :param reason: 刷新原因（用于日志/弹窗提示）
        :return: 新的 captchaVerification，失败返回 None
        """
        self._log_safe(f"\n🔄 自动刷新验证码...\n")
        if reason:
            self._log_safe(f"   原因: {reason}\n")

        solver = CaptchaSolver(max_retries=5, callback=self._log_safe)
        new_token = solver.solve()

        if new_token:
            self.captchaverification.set(new_token)
            self._log_safe(f"✅ 验证码自动获取成功！\n")
            return new_token

        # 自动破解失败，弹窗让用户手动输入
        self._log_safe(f"⚠️ 自动获取失败，请手动输入验证码...\n")
        return self.wait_for_manual_captcha(reason or "自动获取验证码失败")

    def _log_safe(self, msg):
        """线程安全的日志输出"""
        try:
            self.log(msg)
        except Exception:
            print(msg.strip())

    def crawl_thread(self):
        """爬取线程"""
        self.should_stop = False

        try:
            # 如果没有手动填写验证码，则自动获取
            if not self.captchaverification.get().strip():
                self._log_safe("📋 未填写验证码，正在自动获取...\n")
                token = self.auto_refresh_captcha("首次启动")
                if not token:
                    self._log_safe("\n❌ 无法获取验证码，爬取终止\n")
                    return

            mode = self.crawl_mode.get()
            if mode == "page":
                self.crawl_pages_with_captcha_refresh()
            elif mode == "reg":
                self.crawl_registration_numbers_with_captcha_refresh()
            elif mode == "company":
                self.crawl_company_names_with_captcha_refresh()
        except Exception as e:
            self.log(f"\n❌ 爬取过程中出错: {e}\n")
            import traceback
            self.log(traceback.format_exc())
            messagebox.showerror("错误", f"爬取失败: {e}")
        finally:
            # 恢复界面状态
            self.is_crawling = False
            self.should_stop = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.log("\n✅ 爬取完成\n")

    def crawl_pages_with_captcha_refresh(self):
        """按页数爬取，支持验证码刷新"""
        current_page = self.start_page.get()
        end_page = self.end_page.get()
        max_requests = self.max_requests_per_captcha.get()
        limit = self.page_limit.get()

        all_data = []
        all_patents = []

        # 生成一次文件名，整个爬取过程使用同一个文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_dir = self.save_dir.get()
        os.makedirs(save_dir, exist_ok=True)

        if current_page == end_page:
            product_csv = os.path.join(save_dir, f'产品_第{current_page}页_{timestamp}.csv')
            patent_csv = os.path.join(save_dir, f'专利_第{current_page}页_{timestamp}.csv')
        else:
            product_csv = os.path.join(save_dir, f'产品_第{current_page}-{end_page}页_{timestamp}.csv')
            patent_csv = os.path.join(save_dir, f'专利_第{current_page}-{end_page}页_{timestamp}.csv')

        self.log(f"📋 爬取设置: 页码 {current_page}-{end_page}, 每页 {limit} 条, 每 {max_requests} 次请求更换验证码\n")
        self.log(f"📁 数据将保存到:\n   {product_csv}\n   {patent_csv}\n")

        while current_page <= end_page and not self.should_stop:
            # 检查是否需要更新验证码
            if self.current_request_count.get() >= max_requests:
                self.log(f"\n⚠️ 已达到请求次数限制 ({max_requests} 次)，需要更新验证码\n")

                new_captcha = self.auto_refresh_captcha(
                    f"已完成 {self.current_request_count.get()} 次请求\n还剩 {end_page - current_page + 1} 页待爬取"
                )

                if not new_captcha:
                    break

                # 重置请求计数
                self.reset_request_count()

            self.log(f"\n📋 正在爬取第 {current_page} 页\n")

            result = crawl_patents(
                start_page=current_page,
                end_page=current_page,
                limit=limit,
                captchaverification=self.captchaverification.get().strip(),
                save_dir=self.save_dir.get(),
                max_pages_per_captcha=999999,  # 不使用内部限制
                callback=self.log,
                stop_check=lambda: self.should_stop,
                request_counter=self.update_request_count,
                current_count=self.current_request_count.get(),
                product_csv=product_csv,  # 传入固定的文件名
                patent_csv=patent_csv  # 传入固定的文件名
            )

            if self.should_stop:
                break

            status, data, patents = result

            # 检查是否被停止
            if status == 'STOPPED':
                break

            all_data.extend(data)
            all_patents.extend(patents)

            # 检查是否需要更新验证码（API返回错误）
            if status == 'NEED_UPDATE_CAPTCHA':
                self.log(f"\n⚠️ 验证码失效，需要更新验证码\n")

                new_captcha = self.auto_refresh_captcha(
                    f"验证码已失效\n还剩 {end_page - current_page} 页待爬取"
                )

                if not new_captcha:
                    break

                # 重置请求计数
                self.reset_request_count()
                continue

            # 更新当前页码
            current_page += 1

        self.log(f"\n📊 总计爬取 {len(all_data)} 条产品数据，{len(all_patents)} 条专利数据\n")

    def crawl_registration_numbers_with_captcha_refresh(self):
        """按备案号爬取，支持验证码刷新"""
        reg_numbers = self.registration_numbers.copy()
        total_count = len(reg_numbers)
        current_index = 0
        max_requests = self.max_requests_per_captcha.get()

        all_data = []
        all_patents = []

        # 生成一次文件名，整个爬取过程使用同一个文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_dir = self.save_dir.get()
        os.makedirs(save_dir, exist_ok=True)

        product_csv = os.path.join(save_dir, f'产品_按备案号_{timestamp}.csv')
        patent_csv = os.path.join(save_dir, f'专利_按备案号_{timestamp}.csv')

        self.log(f"📋 爬取设置: 共 {total_count} 个备案号, 每 {max_requests} 次请求更换验证码\n")
        self.log(f"📁 数据将保存到:\n   {product_csv}\n   {patent_csv}\n")

        while current_index < total_count and not self.should_stop:
            # 检查是否需要更新验证码
            if self.current_request_count.get() >= max_requests:
                remaining = total_count - current_index
                self.log(f"\n⚠️ 已达到请求次数限制 ({max_requests} 次)，需要更新验证码\n")

                new_captcha = self.auto_refresh_captcha(
                    f"已完成 {self.current_request_count.get()} 次请求\n还剩 {remaining} 个备案号待爬取"
                )

                if not new_captcha:
                    break

                # 重置请求计数
                self.reset_request_count()

            # 爬取单个备案号
            reg_num = reg_numbers[current_index]

            result = crawl_by_registration_numbers(
                registration_numbers=[reg_num],
                captchaverification=self.captchaverification.get().strip(),
                save_dir=self.save_dir.get(),
                max_numbers_per_captcha=999999,  # 不使用内部限制
                callback=self.log,
                stop_check=lambda: self.should_stop,
                request_counter=self.update_request_count,
                current_count=self.current_request_count.get(),
                product_csv=product_csv,  # 传入固定的文件名
                patent_csv=patent_csv  # 传入固定的文件名
            )

            if self.should_stop:
                break

            status, data, patents = result

            # 检查是否被停止
            if status == 'STOPPED':
                break

            all_data.extend(data)
            all_patents.extend(patents)

            # 检查是否需要更新验证码（API返回错误）
            if status == 'NEED_UPDATE_CAPTCHA':
                remaining = total_count - current_index - 1
                self.log(f"\n⚠️ 验证码失效，需要更新验证码\n")

                new_captcha = self.auto_refresh_captcha(
                    f"验证码已失效\n还剩 {remaining} 个备案号待爬取"
                )

                if not new_captcha:
                    break

                # 重置请求计数
                self.reset_request_count()
                continue

            # 更新当前索引
            current_index += 1

        self.log(f"\n📊 总计爬取 {len(all_data)} 条产品数据，{len(all_patents)} 条专利数据\n")

    def crawl_company_names_with_captcha_refresh(self):
        """按公司名称爬取，支持验证码刷新"""
        names = self.company_names.copy()
        total_count = len(names)
        current_index = 0
        max_requests = self.max_requests_per_captcha.get()

        all_data = []
        all_patents = []

        # 生成一次文件名，整个爬取过程使用同一个文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_dir = self.save_dir.get()
        os.makedirs(save_dir, exist_ok=True)

        product_csv = os.path.join(save_dir, f'产品_按公司名称_{timestamp}.csv')
        patent_csv = os.path.join(save_dir, f'专利_按公司名称_{timestamp}.csv')

        self.log(f"📋 爬取设置: 共 {total_count} 个公司名称, 每 {max_requests} 次请求更换验证码\n")
        self.log(f"📁 数据将保存到:\n   {product_csv}\n   {patent_csv}\n")

        while current_index < total_count and not self.should_stop:
            # 检查是否需要更新验证码
            if self.current_request_count.get() >= max_requests:
                remaining = total_count - current_index
                self.log(f"\n⚠️ 已达到请求次数限制 ({max_requests} 次)，需要更新验证码\n")

                new_captcha = self.auto_refresh_captcha(
                    f"已完成 {self.current_request_count.get()} 次请求\n还剩 {remaining} 个公司名称待爬取"
                )

                if not new_captcha:
                    break

                # 重置请求计数
                self.reset_request_count()

            # 爬取单个公司
            company_name = names[current_index]

            result = crawl_by_company_names(
                company_names=[company_name],
                captchaverification=self.captchaverification.get().strip(),
                save_dir=self.save_dir.get(),
                max_numbers_per_captcha=999999,  # 不使用内部限制
                callback=self.log,
                stop_check=lambda: self.should_stop,
                request_counter=self.update_request_count,
                current_count=self.current_request_count.get(),
                product_csv=product_csv,  # 传入固定的文件名
                patent_csv=patent_csv  # 传入固定的文件名
            )

            if self.should_stop:
                break

            status, data, patents = result

            # 检查是否被停止
            if status == 'STOPPED':
                break

            all_data.extend(data)
            all_patents.extend(patents)

            # 检查是否需要更新验证码（API返回错误）
            if status == 'NEED_UPDATE_CAPTCHA':
                remaining = total_count - current_index - 1
                self.log(f"\n⚠️ 验证码失效，需要更新验证码\n")

                new_captcha = self.auto_refresh_captcha(
                    f"验证码已失效\n还剩 {remaining} 个公司名称待爬取"
                )

                if not new_captcha:
                    break

                # 重置请求计数
                self.reset_request_count()
                continue

            # 更新当前索引
            current_index += 1

        self.log(f"\n📊 总计爬取 {len(all_data)} 条产品数据，{len(all_patents)} 条专利数据\n")

    def stop_crawl(self):
        """停止爬取"""
        if messagebox.askyesno("确认", "确定要停止爬取吗？"):
            self.is_crawling = False
            self.should_stop = True
            # 如果正在等待验证码输入，也要唤醒线程
            self.new_captcha_result = None
            self.captcha_dialog_event.set()
            self.log("\n⏹️ 用户停止爬取\n")

    def request_manual_captcha(self, reason="验证码已达到使用限制"):
        """在主线程中弹窗请求新验证码（仅在自动破解失败时调用）"""
        from tkinter import simpledialog

        new_captcha = simpledialog.askstring(
            "需要手动输入验证码",
            f"{reason}\n\n自动获取验证码失败，请手动输入：\n"
            f"（打开浏览器F12获取 captchaverification 值）\n"
            f"（点击取消将停止爬取）",
            parent=self.root,
            initialvalue=""
        )

        self.new_captcha_result = new_captcha.strip() if new_captcha else None
        self.captcha_dialog_event.set()

    def wait_for_manual_captcha(self, reason="自动获取验证码失败"):
        """在工作线程中等待用户手动输入验证码（备用方案）"""
        self.captcha_dialog_event.clear()
        self.new_captcha_result = None

        # 在主线程中显示对话框
        self.root.after(0, lambda: self.request_manual_captcha(reason))

        # 等待用户输入
        self.captcha_dialog_event.wait()

        if self.new_captcha_result:
            self.captchaverification.set(self.new_captcha_result)
            self._log_safe(f"\n✅ 已手动更新验证码参数，继续爬取...\n")
            return self.new_captcha_result
        else:
            self._log_safe("\n⏹️ 用户取消输入验证码，停止爬取\n")
            return None


if __name__ == '__main__':
    root = tk.Tk()
    app = CrawlerGUI(root)
    root.mainloop()

