import time
from DrissionPage import ChromiumPage
from DrissionPage.common import Actions

# ============ 配置 ============
SKIP_USERNAME = "大学生的希望"    # 碰到这个用户名的评论就跳过不回复
REPLY_CONTENT = "可以找窝这样子先干活的呀"       # 回复内容
MAX_PARENT_COMMENTS = 5         # 每个笔记最多处理几条父评论
MAX_NOTES = 5                   # 最多处理几个笔记


def open_search_page(page, url):
    """打开搜索页面"""
    page.get(url)
    page.wait.load_start()
    time.sleep(2)


def post_main_comment(page, content=REPLY_CONTENT):
    """在评论区底部输入框发表主评论"""
    try:
        comment_input = page.ele('css:#noteContainer div.interaction-area input[placeholder]', timeout=2)
        if not comment_input:
            comment_input = page.ele('xpath://div[contains(@class,"comment")]//input', timeout=2)
        if not comment_input:
            comment_input = page.ele('css:#noteContainer div.interaction-area div[contenteditable="true"]', timeout=2)

        if comment_input:
            comment_input.click()
            time.sleep(0.5)
            comment_input.input(content)
            time.sleep(0.3)
        else:
            comment_area = page.ele('text:说点什么', timeout=1)
            if comment_area:
                comment_area.click()
                time.sleep(0.5)
                active_input = page.ele(
                    'css:div[contenteditable="true"]:focus, input:focus, textarea:focus',)
                if active_input:
                    active_input.input(content)
                else:
                    Actions(page).type(content)
                time.sleep(0.3)
            else:
                print("  未找到评论输入框")
                return False

        send_btn = page.ele('text:发送', timeout=2)
        if send_btn:
            send_btn.click()
            print("  已发表主评论")
        else:
            Actions(page).key_down('Enter').key_up('Enter')
            print("  未找到发送按钮，已尝试回车发送")
        time.sleep(1)
        return True
    except Exception as e:
        print(f"  发表主评论失败: {e}")
        return False


def dismiss_reply_input(page):
    """点击"共N条评论"标题区域来取消回复输入框焦点。
    绝对不能用Escape——Escape会关闭整个笔记弹窗。"""
    try:
        total_el = page.ele('css:.comments-container .total', timeout=1)
        if total_el:
            total_el.click()
            time.sleep(0.3)
            return
        container = page.ele('css:.comments-container', timeout=1)
        if container:
            container.click()
            time.sleep(0.3)
    except:
        pass


def get_comment_username(comment_item):
    """从一个 comment-item 元素中提取用户名（a.name 的文本）"""
    try:
        name_el = comment_item.ele('css:.author a.name', timeout=1)
        if name_el:
            return (name_el.text or '').strip()
    except:
        pass
    return ''


def click_reply_and_send(page, reply_btn, content=REPLY_CONTENT):
    """点击一个回复按钮 → 输入内容 → 发送 → 取消焦点
    返回 True/False 表示是否成功"""
    try:
        reply_btn.click()
        time.sleep(0.8)

        # 找到被激活的输入框
        reply_input = page.ele(
            'css:div[contenteditable="true"]:focus, input:focus, textarea:focus', timeout=2)
        if not reply_input:
            reply_input = page.ele(
                'css:#noteContainer div.interaction-area input[placeholder]', timeout=1)
        if not reply_input:
            reply_input = page.ele('css:div[contenteditable="true"]', timeout=1)

        if reply_input:
            reply_input.click()
            time.sleep(0.3)
            reply_input.input(content)
        else:
            Actions(page).type(content)
        time.sleep(0.3)

        # 点击发送
        send_btn = page.ele('text:发送', timeout=2)
        if send_btn:
            send_btn.click()
        else:
            Actions(page).key_down('Enter').key_up('Enter')

        time.sleep(1)
        # 取消回复框焦点，为下一次回复做准备
        dismiss_reply_input(page)
        return True
    except Exception as e:
        print(f"    发送失败: {e}")
        dismiss_reply_input(page)
        return False


def get_fresh_parent_comment(page, index):
    """重新从页面获取第 index 个 parent-comment（0-based），
    避免因DOM变化导致元素引用失效。"""
    pcs = page.eles('css:.parent-comment', timeout=5)
    if pcs and index < len(pcs):
        return pcs[index]
    return None


def process_parent_comments(page, max_count=MAX_PARENT_COMMENTS, content=REPLY_CONTENT):
    """对前 max_count 条父评论进行处理：
    1. 回复父评论本身（跳过自己的评论）
    2. 如果有 div.show-more "展开N条回复" 按钮则点击展开
    3. 回复所有子评论 .comment-item-sub（跳过自己的评论）
    """
    parent_comments = page.eles('css:.parent-comment', timeout=3)
    if not parent_comments:
        print("  未找到父评论")
        return

    total = min(max_count, len(parent_comments))
    print(f"  共找到 {len(parent_comments)} 条父评论，将处理前 {total} 条")

    replied_count = 0  # 实际成功回复计数

    for i in range(total):
        try:
            pc = get_fresh_parent_comment(page, i)
            if not pc:
                print(f"  父评论 #{i+1}: 已不存在，跳过")
                break

            # ====== 第1步：回复父评论本身 ======
            first_item = pc.ele('css:.comment-item', timeout=1)
            if not first_item:
                print(f"  父评论 #{i+1}: 未找到 comment-item，跳过")
                continue

            # 检查用户名，跳过自己
            username = get_comment_username(first_item)
            if SKIP_USERNAME in username:
                print(f"  父评论 #{i+1}: 用户名「{username}」包含「{SKIP_USERNAME}」，跳过")
                continue

            # 找回复按钮：div.reply.icon-container
            reply_btn = first_item.ele('css:.reply.icon-container', timeout=1)
            if not reply_btn:
                reply_btn = first_item.ele(
                    'xpath:.//div[contains(@class,"interactions")]//div[contains(@class,"reply")]',
                    timeout=2)

            if reply_btn:
                print(f"  父评论 #{i+1}「{username}」: 回复中...")
                if click_reply_and_send(page, reply_btn, content):
                    replied_count += 1
                    print(f"  父评论 #{i+1}: 已回复 ✓")
            else:
                print(f"  父评论 #{i+1}: 未找到回复按钮，跳过")
                continue

            # ====== 第2步：展开子评论 ======
            # div.show-more 在 div.reply-container 内，文本为 "展开 N 条回复"
            pc = get_fresh_parent_comment(page, i)
            if not pc:
                break

            # 循环点击展开，直到没有更多
            for expand_round in range(10):
                try:
                    show_more = pc.ele('css:.show-more', timeout=1)
                    if show_more and '展开' in (show_more.text or ''):
                        print(f"  父评论 #{i+1}: {show_more.text.strip()}")
                        show_more.click()
                        time.sleep(1)
                        # 重新获取 pc
                        pc = get_fresh_parent_comment(page, i)
                        if not pc:
                            break
                    else:
                        break
                except:
                    break

            # ====== 第3步：回复所有子评论 ======
            pc = get_fresh_parent_comment(page, i)
            if not pc:
                break

            # 子评论的class是 "comment-item comment-item-sub"，在 reply-container 内
            sub_comments = pc.eles('css:.comment-item-sub', timeout=2)
            if sub_comments:
                print(f"  父评论 #{i+1}: 发现 {len(sub_comments)} 条子评论")
                for j in range(len(sub_comments)):
                    try:
                        # 每次重新获取，防止DOM变化
                        pc = get_fresh_parent_comment(page, i)
                        if not pc:
                            break
                        subs = pc.eles('css:.comment-item-sub', timeout=2)
                        if j >= len(subs):
                            break

                        sub_item = subs[j]

                        # 检查子评论用户名，跳过自己
                        sub_username = get_comment_username(sub_item)
                        if SKIP_USERNAME in sub_username:
                            print(f"    子评论 #{j+1}: 用户名「{sub_username}」包含「{SKIP_USERNAME}」，跳过")
                            continue

                        sub_reply_btn = sub_item.ele('css:.reply.icon-container', timeout=1)
                        if not sub_reply_btn:
                            sub_reply_btn = sub_item.ele(
                                'xpath:.//div[contains(@class,"interactions")]//div[contains(@class,"reply")]',
                                timeout=1)

                        if sub_reply_btn:
                            print(f"    子评论 #{j+1}「{sub_username}」: 回复中...")
                            if click_reply_and_send(page, sub_reply_btn, content):
                                replied_count += 1
                                print(f"    子评论 #{j+1}: 已回复 ✓")
                        else:
                            print(f"    子评论 #{j+1}: 未找到回复按钮")
                    except Exception as e:
                        print(f"    子评论 #{j+1}: 回复失败 - {e}")
                        continue

        except Exception as e:
            print(f"  处理父评论 #{i+1} 失败: {e}")
            continue

    print(f"  回复完成，共成功回复 {replied_count} 条")


def close_note_popup(page):
    """关闭笔记弹窗"""
    try:
        close_btn = page.ele('css:div.close-circle, div.close-box', timeout=3)
        if not close_btn:
            close_btn = page.ele('xpath://div[contains(@class,"close")]', timeout=2)
        if close_btn:
            close_btn.click()
            time.sleep(0.5)
    except Exception as e:
        print(f"关闭弹窗失败: {e}")


if __name__ == '__main__':
    search_url = ('https://www.xiaohongshu.com/search_result?'
                  'keyword=计算机毕业设计'
                  '&source=web_profile_page')

    page = ChromiumPage()
    print("正在打开搜索页面...")
    open_search_page(page, search_url)

    cards = page.eles('xpath://*[@id="global"]/div[2]/div[2]/div/div/div[3]/div[1]/section')
    if not cards:
        print("未找到笔记卡片，请检查页面是否正常加载")
        exit()

    max_notes = min(MAX_NOTES, len(cards))
    print(f"共找到 {len(cards)} 个笔记，将处理前 {max_notes} 个")

    processed = set()
    for note_idx in range(max_notes):
        try:
            cards = page.eles('xpath://*[@id="global"]/div[2]/div[2]/div/div/div[3]/div[1]/section')
            if note_idx >= len(cards):
                break

            card = cards[note_idx]
            index = card.attr('data-index')
            if index in processed:
                continue
            processed.add(index)

            print(f"\n===== 处理第 {note_idx + 1} 个笔记 =====")
            card.ele('xpath:./div/a[2]/img').click(by_js=True)
            time.sleep(1)

            # 步骤1：发表主评论
            print("步骤1: 发表主评论...")
            post_main_comment(page, content=REPLY_CONTENT)

            # 步骤2：回复前N条父评论（含展开子评论并回复）
            print("步骤2: 回复评论...")
            process_parent_comments(page, max_count=MAX_PARENT_COMMENTS, content=REPLY_CONTENT)

            # 关闭弹窗
            close_note_popup(page)
            time.sleep(1)

        except Exception as e:
            print(f"处理第 {note_idx + 1} 个笔记失败: {e}")
            close_note_popup(page)
            time.sleep(1)
            continue

    print("\n全部处理完成!")
