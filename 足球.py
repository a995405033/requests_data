"""
足球数据采集脚本 - 完整版
数据源：
  1. Football-Data.org API — 当前赛季积分榜、赛程赛果、射手榜
  2. Understat（understatapi库）— 五大联赛五个赛季的球员高级统计 + 球队逐场数据
依赖安装：pip install understatapi requests
"""

import requests
import csv
import time
import random
import os
from understatapi import UnderstatClient

# 创建数据存放目录
DATA_DIR = "足球数据集"
os.makedirs(DATA_DIR, exist_ok=True)


# ============================================================
# 通用工具
# ============================================================
def save_to_csv(data, filename):
    if not data:
        print(f"  [跳过] {filename} 无数据")
        return
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    print(f"  [完成] {filename}，共 {len(data)} 条")


def polite_sleep(min_sec=2, max_sec=4):
    time.sleep(random.uniform(min_sec, max_sec))


# ============================================================
# Football-Data.org 配置
# ============================================================
FOOTBALL_DATA_API_KEY = "c3f5987e7a6f45cda53316bfc081fa5b"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
FOOTBALL_DATA_HEADERS = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}

LEAGUE_CODES = {
    "英超": "PL", "西甲": "PD", "德甲": "BL1",
    "意甲": "SA", "法甲": "FL1",
}


# ============================================================
# Football-Data.org 采集函数
# ============================================================
def fetch_standings(league_code):
    """积分榜"""
    url = f"{FOOTBALL_DATA_BASE}/competitions/{league_code}/standings"
    resp = requests.get(url, headers=FOOTBALL_DATA_HEADERS)
    if resp.status_code != 200:
        print(f"  积分榜请求失败: {resp.status_code}")
        return []
    table = resp.json()["standings"][0]["table"]
    return [{
        "排名": t["position"], "球队": t["team"]["name"],
        "场次": t["playedGames"], "胜": t["won"], "平": t["draw"], "负": t["lost"],
        "进球": t["goalsFor"], "失球": t["goalsAgainst"],
        "净胜球": t["goalDifference"], "积分": t["points"],
    } for t in table]


def fetch_scorers(league_code, limit=50):
    """射手榜"""
    url = f"{FOOTBALL_DATA_BASE}/competitions/{league_code}/scorers"
    resp = requests.get(url, headers=FOOTBALL_DATA_HEADERS, params={"limit": limit})
    if resp.status_code != 200:
        print(f"  射手榜请求失败: {resp.status_code}")
        return []
    return [{
        "球员": s["player"]["name"],
        "出生日期": s["player"].get("dateOfBirth", ""),
        "国籍": s["player"].get("nationality", ""),
        "位置": s["player"].get("position", ""),
        "球队": s.get("team", {}).get("name", ""),
        "进球": s.get("goals", 0), "助攻": s.get("assists", 0),
        "出场次数": s.get("playedMatches", 0),
    } for s in resp.json().get("scorers", [])]


def fetch_all_matches(league_code):
    """全赛季赛程"""
    url = f"{FOOTBALL_DATA_BASE}/competitions/{league_code}/matches"
    resp = requests.get(url, headers=FOOTBALL_DATA_HEADERS)
    if resp.status_code != 200:
        print(f"  赛程请求失败: {resp.status_code}")
        return []
    result = []
    for m in resp.json().get("matches", []):
        ft = m.get("score", {}).get("fullTime", {})
        result.append({
            "比赛日": m.get("matchday"), "日期": m.get("utcDate", "")[:10],
            "主队": m["homeTeam"]["name"], "客队": m["awayTeam"]["name"],
            "主队进球": ft.get("home", ""), "客队进球": ft.get("away", ""),
            "状态": m["status"],
        })
    return result


# ============================================================
# Understat 采集函数（通过 understatapi 库）
# ============================================================
UNDERSTAT_LEAGUES = {
    "英超": "EPL", "西甲": "La_Liga", "德甲": "Bundesliga",
    "意甲": "Serie_A", "法甲": "Ligue_1",
}

# 五个赛季：2020-21 到 2024-25
SEASONS = ["2020", "2021", "2022", "2023", "2024"]


def fetch_understat_players(client, league_key, league_name, season):
    """获取某联赛某赛季的球员高级统计"""
    raw = client.league(league=league_key).get_player_data(season=season)
    result = []
    for p in raw:
        result.append({
            "联赛": league_name, "赛季": f"{season}-{int(season)+1}",
            "球员": p.get("player_name", ""),
            "位置": p.get("position", ""),
            "球队": p.get("team_title", ""),
            "出场": p.get("games", 0),
            "出场时间": p.get("time", 0),
            "进球": p.get("goals", 0),
            "助攻": p.get("assists", 0),
            "xG": p.get("xG", 0),
            "xA": p.get("xA", 0),
            "射门": p.get("shots", 0),
            "关键传球": p.get("key_passes", 0),
            "黄牌": p.get("yellow_cards", 0),
            "红牌": p.get("red_cards", 0),
            "非点球进球": p.get("npg", 0),
            "非点球xG": p.get("npxG", 0),
            "xG链": p.get("xGChain", 0),
            "xG组织": p.get("xGBuildup", 0),
        })
    return result


def fetch_understat_team_matches(client, league_key, league_name, season):
    """获取某联赛某赛季所有球队的逐场比赛数据（用于趋势折线图）"""
    raw = client.league(league=league_key).get_team_data(season=season)
    result = []
    # raw 是 dict，key 是球队ID，value 是球队信息
    for team_id, team_info in raw.items():
        team_name = team_info.get("title", "")
        for match in team_info.get("history", []):
            ppda = match.get("ppda", {})
            result.append({
                "联赛": league_name, "赛季": f"{season}-{int(season)+1}",
                "球队": team_name,
                "比赛日期": match.get("date", ""),
                "主客场": "主场" if match.get("h_a") == "h" else "客场",
                "进球": match.get("scored", 0),
                "失球": match.get("missed", 0),
                "结果": match.get("result", ""),
                "xG": match.get("xG", 0),
                "xGA": match.get("xGA", 0),
                "积分": match.get("pts", 0),
                "PPDA进攻": ppda.get("att", 0),
                "PPDA防守": ppda.get("def", 0),
            })
    return result


# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    target_leagues = ["英超", "西甲", "德甲", "意甲", "法甲"]

    # ----------------------------------------------------------
    # 第一部分：Football-Data.org（当前赛季）
    # ----------------------------------------------------------
    if FOOTBALL_DATA_API_KEY:
        print("=" * 60)
        print("【第一部分】Football-Data.org 当前赛季数据")
        print("=" * 60)
        for lg in target_leagues:
            code = LEAGUE_CODES.get(lg)
            if not code:
                continue
            print(f"\n>>> {lg}")
            save_to_csv(fetch_standings(code), f"{DATA_DIR}/{lg}_积分榜.csv")
            polite_sleep(6, 8)
            save_to_csv(fetch_scorers(code, 50), f"{DATA_DIR}/{lg}_射手榜.csv")
            polite_sleep(6, 8)
            save_to_csv(fetch_all_matches(code), f"{DATA_DIR}/{lg}_赛程.csv")
            polite_sleep(6, 8)

    # ----------------------------------------------------------
    # 第二部分：Understat 五大联赛 × 五个赛季
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print("【第二部分】Understat 五大联赛五个赛季数据")
    print(f"联赛：{target_leagues}")
    print(f"赛季：2020-21 ~ 2024-25")
    print("=" * 60)

    all_players = []
    all_team_matches = []

    with UnderstatClient() as understat:
        for lg_name in target_leagues:
            lg_key = UNDERSTAT_LEAGUES.get(lg_name)
            if not lg_key:
                continue

            for season in SEASONS:
                tag = f"{lg_name} {season}-{int(season)+1}"
                print(f"\n>>> {tag} 球员数据...")
                try:
                    players = fetch_understat_players(understat, lg_key, lg_name, season)
                    all_players.extend(players)
                    print(f"  拿到 {len(players)} 条")
                except Exception as e:
                    print(f"  球员数据出错: {e}")
                polite_sleep()

                print(f">>> {tag} 球队逐场数据...")
                try:
                    matches = fetch_understat_team_matches(understat, lg_key, lg_name, season)
                    all_team_matches.extend(matches)
                    print(f"  拿到 {len(matches)} 条")
                except Exception as e:
                    print(f"  球队数据出错: {e}")
                polite_sleep()

    save_to_csv(all_players, f"{DATA_DIR}/五大联赛_球员统计_5赛季_Understat.csv")
    save_to_csv(all_team_matches, f"{DATA_DIR}/五大联赛_球队逐场数据_5赛季_Understat.csv")

    # ----------------------------------------------------------
    # 汇总
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print("全部采集完成")
    print("=" * 60)
    if FOOTBALL_DATA_API_KEY:
        print("Football-Data.org（当前赛季）:")
        for lg in target_leagues:
            print(f"  {DATA_DIR}/{lg}_积分榜.csv / {lg}_射手榜.csv / {lg}_赛程.csv")
    print(f"Understat 球员统计: {len(all_players)} 条（五大联赛×五赛季）")
    print(f"Understat 球队逐场: {len(all_team_matches)} 条")
