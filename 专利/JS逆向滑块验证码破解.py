"""
测试自动获取 captchaVerification
使用 OpenCV 模板匹配识别滑块拼图缺口位置
"""

import requests
import json
import base64
import uuid
import time
import numpy as np
import cv2
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


# 网站使用的自定义验证码类型（从前端 JS 源码中提取）
CAPTCHA_TYPE = "zlcpBlockPuzzle"

# 公共请求头
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


def compact_json(obj):
    """
    生成与 JavaScript JSON.stringify 一致的紧凑 JSON（无空格）
    Python 默认: {"x": 246, "y": 5}
    JS 风格:    {"x":246,"y":5}
    """
    return json.dumps(obj, separators=(",", ":"))


def aes_ecb_encrypt(plaintext, key):
    """
    AES-128-ECB 加密（PKCS7 填充），返回 Base64 字符串
    与前端 CryptoJS AES ECB 加密逻辑一致
    """
    key_bytes = key.encode("utf-8")
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def detect_gap_position(bg_b64, slider_b64):
    """
    使用 OpenCV 边缘检测 + 模板匹配，找到滑块缺口的 X 坐标
    """
    # 解码 Base64 图片
    bg_bytes = base64.b64decode(bg_b64)
    slider_bytes = base64.b64decode(slider_b64)

    bg_arr = np.frombuffer(bg_bytes, np.uint8)
    slider_arr = np.frombuffer(slider_bytes, np.uint8)

    bg_img = cv2.imdecode(bg_arr, cv2.IMREAD_COLOR)
    slider_img = cv2.imdecode(slider_arr, cv2.IMREAD_UNCHANGED)

    if bg_img is None:
        raise ValueError("背景图解码失败")
    if slider_img is None:
        raise ValueError("滑块图解码失败")

    print(f"  背景图尺寸: {bg_img.shape}")
    print(f"  滑块图尺寸: {slider_img.shape}")

    # 如果滑块图有 alpha 通道，提取有效区域
    if slider_img.shape[2] == 4:
        alpha = slider_img[:, :, 3]
        slider_bgr = slider_img[:, :, :3]

        # 找到非透明区域的边界并裁剪
        rows = np.any(alpha > 0, axis=1)
        cols = np.any(alpha > 0, axis=0)
        if rows.any() and cols.any():
            rmin, rmax = np.where(rows)[0][[0, -1]]
            cmin, cmax = np.where(cols)[0][[0, -1]]
            slider_crop = slider_bgr[rmin:rmax + 1, cmin:cmax + 1]
            mask_crop = alpha[rmin:rmax + 1, cmin:cmax + 1]
            print(f"  裁剪后滑块尺寸: {slider_crop.shape}")
        else:
            slider_crop = slider_bgr
            mask_crop = alpha
    else:
        slider_crop = slider_img
        mask_crop = None

    # 方法1：边缘检测 + 模板匹配
    bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
    slider_gray = cv2.cvtColor(slider_crop, cv2.COLOR_BGR2GRAY)

    bg_edge = cv2.Canny(bg_gray, 100, 200)
    slider_edge = cv2.Canny(slider_gray, 100, 200)

    result = cv2.matchTemplate(bg_edge, slider_edge, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    gap_x = max_loc[0]
    print(f"  边缘匹配置信度: {max_val:.4f}, 位置: x={gap_x}")

    # 方法2：灰度 + mask 模板匹配（通常更准确）
    if mask_crop is not None:
        result2 = cv2.matchTemplate(bg_gray, slider_gray, cv2.TM_CCOEFF_NORMED, mask=mask_crop)
        _, max_val2, _, max_loc2 = cv2.minMaxLoc(result2)
        gap_x2 = max_loc2[0]
        print(f"  灰度+mask匹配置信度: {max_val2:.4f}, 位置: x={gap_x2}")

        if max_val2 > max_val:
            print(f"  -> 使用灰度+mask匹配结果: x={gap_x2}")
            gap_x = gap_x2

    return gap_x


def get_captcha_verification(max_retries=5):
    """
    自动获取 captchaVerification

    流程：
    1. POST /opc/api/captcha/get → 获取背景图、滑块图、token、secretKey
    2. OpenCV 识别缺口 X 坐标
    3. POST /opc/api/captcha/check → AES加密坐标并校验
    4. 本地计算 captchaVerification = AES(token + "---" + pointJson, secretKey)
    """
    for attempt in range(1, max_retries + 1):
        print(f"\n{'='*50}")
        print(f"第 {attempt}/{max_retries} 次尝试获取验证码...")
        print(f"{'='*50}")

        try:
            # ========== 第1步：获取验证码图片 ==========
            print("\n[步骤1] 获取验证码图片...")
            client_uid = "slider-" + str(uuid.uuid4())
            ts = int(time.time() * 1000)

            get_resp = requests.post(
                "https://api.zlcp.org.cn/opc/api/captcha/get",
                headers=COMMON_HEADERS,
                json={
                    "captchaType": CAPTCHA_TYPE,
                    "clientUid": client_uid,
                    "ts": ts
                },
                timeout=15
            )
            print(f"  响应状态: {get_resp.status_code}")
            print(f"  响应长度: {len(get_resp.text)}")

            if not get_resp.text.strip():
                print(f"  ❌ 响应为空")
                continue

            get_data = get_resp.json()
            resp_code = get_data.get("code", get_data.get("repCode", "N/A"))
            print(f"  响应 code: {resp_code}")

            # 兼容两种响应格式
            captcha_data = get_data.get("data") or get_data.get("repData")
            if not captcha_data:
                print(f"  ❌ 获取验证码失败: {json.dumps(get_data, ensure_ascii=False)[:200]}")
                time.sleep(2)
                continue

            token = captcha_data["token"]
            secret_key = captcha_data["secretKey"]
            bg_b64 = captcha_data["originalImageBase64"]
            slider_b64 = captcha_data["jigsawImageBase64"]

            print(f"  ✅ token: {token[:20]}...")
            print(f"  ✅ secretKey: {secret_key}")

            # ========== 第2步：识别缺口位置 ==========
            print("\n[步骤2] 识别缺口位置...")
            gap_x = detect_gap_position(bg_b64, slider_b64)
            print(f"  最终识别缺口 x = {gap_x}")

            # 模拟人类操作的延迟（滑动需要时间）
            time.sleep(1)

            # ========== 第3步：AES 加密并校验 ==========
            print("\n[步骤3] 校验验证码...")

            # 坐标 JSON — 必须使用紧凑格式（与 JS 的 JSON.stringify 一致）
            point = {"x": gap_x, "y": 5}
            point_json_str = compact_json(point)
            encrypted_point = aes_ecb_encrypt(point_json_str, secret_key)

            print(f"  pointJson 明文: {point_json_str}")
            print(f"  pointJson 密文: {encrypted_point[:40]}...")

            check_resp = requests.post(
                "https://api.zlcp.org.cn/opc/api/captcha/check",
                headers=COMMON_HEADERS,
                json={
                    "captchaType": CAPTCHA_TYPE,
                    "pointJson": encrypted_point,
                    "token": token
                },
                timeout=15
            )
            check_data = check_resp.json()
            check_code = check_data.get("code", check_data.get("repCode"))
            print(f"  校验响应 code: {check_code}")
            print(f"  校验响应: {json.dumps(check_data, ensure_ascii=False)[:300]}")

            # 判断校验是否成功
            success = (check_code == 0 or check_code == "0000")
            if not success:
                msg = check_data.get("message", "")
                print(f"  ❌ 校验失败: {msg}")
                time.sleep(2)
                continue

            # ========== 第4步：生成 captchaVerification ==========
            print("\n[步骤4] 生成 captchaVerification...")
            raw = token + "---" + compact_json({"x": gap_x, "y": 5})
            captcha_verification = aes_ecb_encrypt(raw, secret_key)

            print(f"  ✅ captchaVerification: {captcha_verification[:60]}...")
            return captcha_verification

        except Exception as e:
            print(f"  ❌ 出错: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(2)

    print(f"\n❌ {max_retries} 次尝试全部失败")
    return None


def test_api_with_token(captcha_verification):
    """
    用获取到的 captchaVerification 测试实际 API 调用
    """
    print(f"\n{'='*50}")
    print("测试 API 调用...")
    print(f"{'='*50}")

    headers = {
        **COMMON_HEADERS,
        "captchaverification": captcha_verification,
    }

    # ---------- 测试1: 列表接口 ----------
    print("\n[测试1] 列表接口 /eszlcp/api/es/pro/page")
    payload = {
        "isPub": None,
        "limit": 10,
        "page": 1,
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
        resp = requests.post(
            "https://api.zlcp.org.cn/eszlcp/api/es/pro/page",
            headers=headers,
            json=payload,
            timeout=30
        )
        data = resp.json()
        code = data.get("code")
        print(f"  响应 code: {code}")
        if code == 0 and data.get("data"):
            total = data["data"].get("total", "N/A")
            list_count = len(data["data"].get("list", []))
            print(f"  ✅ 成功！总记录数: {total}, 本页返回: {list_count} 条")
            if list_count > 0:
                first = data["data"]["list"][0]
                print(f"  第一条: {first.get('productName', 'N/A')} - {first.get('productNum', 'N/A')}")
        else:
            msg = data.get("message", data.get("msg", ""))
            print(f"  ❌ 失败: {msg}")
            print(f"  完整响应: {json.dumps(data, ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"  ❌ 请求出错: {e}")

    # ---------- 测试2: 详情接口（参数通过 URL query 传递） ----------
    print("\n[测试2] 详情接口 /eszlcp/api/es/pro/detail")
    try:
        detail_params = {
            "productGuid": "2c8b39fb-dd8a-4485-aae4-8aa8eaad9410",
            "y": 2025
        }
        resp = requests.post(
            "https://api.zlcp.org.cn/eszlcp/api/es/pro/detail",
            headers=headers,
            params=detail_params,
            json={},
            timeout=30
        )
        data = resp.json()
        code = data.get("code")
        print(f"  响应 code: {code}")
        if code == 0 and data.get("data"):
            product_name = data["data"].get("productName", "N/A")
            pat_total = data["data"].get("patTotal", "N/A")
            print(f"  ✅ 成功！产品: {product_name}, 专利数: {pat_total}")
        else:
            msg = data.get("message", data.get("msg", ""))
            print(f"  ❌ 失败: {msg}")
            print(f"  完整响应: {json.dumps(data, ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"  ❌ 请求出错: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("  专利平台验证码自动获取测试")
    print("  使用 OpenCV 边缘检测 + 模板匹配")
    print("=" * 60)

    token = get_captcha_verification(max_retries=5)

    if token:
        print(f"\n{'='*60}")
        print(f"✅ 获取成功！")
        print(f"captchaVerification = {token}")
        print(f"{'='*60}")

        test_api_with_token(token)
    else:
        print("\n❌ 获取失败，请检查网络或重试")
