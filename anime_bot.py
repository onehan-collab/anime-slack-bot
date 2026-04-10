#!/usr/bin/env python3
"""
분기별 신작 애니메이션 Slack 알림 봇
AniList API → Slack chat.write
"""

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime

# ── 설정 ──────────────────────────────────────────────
# 깃허브에 올릴 때 토큰이 유출되지 않도록 환경 변수만 사용합니다.
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL   = os.environ.get("SLACK_CHANNEL", "#xyz_test")   # 발송할 채널

if not SLACK_BOT_TOKEN:
    raise ValueError("보안을 위해 SLACK_BOT_TOKEN 환경 변수가 필요합니다. (GitHub Secrets에 등록해주세요)")
TOP_N           = 10           # 상위 몇 개 애니 알림할지
# ──────────────────────────────────────────────────────

def get_current_season():
    """현재 분기 계산"""
    month = datetime.now().month
    year  = datetime.now().year
    season_map = {
        (1, 2, 3):  "WINTER",
        (4, 5, 6):  "SPRING",
        (7, 8, 9):  "SUMMER",
        (10, 11, 12): "FALL",
    }
    for months, season in season_map.items():
        if month in months:
            return season, year
    return "WINTER", year


def fetch_anime(season: str, year: int, top_n: int) -> list[dict]:
    """AniList GraphQL API로 분기 인기 애니 조회"""
    query = """
    query ($season: MediaSeason, $year: Int, $perPage: Int) {
      Page(perPage: $perPage) {
        media(
          season: $season
          seasonYear: $year
          type: ANIME
          sort: POPULARITY_DESC
          status_in: [RELEASING, NOT_YET_RELEASED]
        ) {
          title { romaji native }
          episodes
          status
          averageScore
          popularity
          genres
          studios(isMain: true) { nodes { name } }
          siteUrl
          coverImage { large }
          description(asHtml: false)
          startDate { year month day }
          nextAiringEpisode { episode airingAt }
        }
      }
    }
    """
    variables = {"season": season, "year": year, "perPage": top_n}
    payload   = json.dumps({"query": query, "variables": variables}).encode()

    req = urllib.request.Request(
        "https://graphql.anilist.co",
        data    = payload,
        headers = {
            "Content-Type": "application/json", 
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        },
        method  = "POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    return data["data"]["Page"]["media"]


def format_status(status: str) -> str:
    return {"RELEASING": "방영중 📺", "NOT_YET_RELEASED": "방영예정 🔜"}.get(status, status)


def format_date(d: dict) -> str:
    if not d or not d.get("year"):
        return "미정"
    return f"{d['year']}.{d['month']:02d}.{d['day']:02d}"


def build_slack_blocks(anime_list: list[dict], season: str, year: int) -> list:
    """Slack Block Kit 메시지 구성"""
    season_kr = {"WINTER": "❄️ 겨울", "SPRING": "🌸 봄", "SUMMER": "☀️ 여름", "FALL": "🍂 가을"}
    label = season_kr.get(season, season)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎌 {year}년 {label} 분기 신작 애니메이션 TOP {len(anime_list)}"}
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*{datetime.now().strftime('%Y-%m-%d')}* 기준 · AniList 인기순"}]
        },
        {"type": "divider"},
    ]

    for i, anime in enumerate(anime_list, 1):
        title_romaji = anime["title"]["romaji"]
        title_native = anime["title"]["native"] or ""
        score    = anime["averageScore"] or "?"
        genres   = " · ".join(anime["genres"][:3]) if anime["genres"] else "—"
        studio   = anime["studios"]["nodes"][0]["name"] if anime["studios"]["nodes"] else "—"
        status   = format_status(anime["status"])
        episodes = f"{anime['episodes']}화" if anime["episodes"] else "미정"
        url      = anime["siteUrl"]

        # 다음 방영 정보
        nae = anime.get("nextAiringEpisode")
        if nae:
            from datetime import timezone
            next_ep   = nae["episode"]
            airing_ts = nae["airingAt"]
            airing_dt = datetime.fromtimestamp(airing_ts).strftime("%m/%d %H:%M")
            next_info = f"다음 방영: {next_ep}화 ({airing_dt})"
        else:
            next_info = ""

        # 줄거리 (100자 제한)
        desc = anime.get("description") or ""
        desc = desc[:100].replace("\n", " ") + ("…" if len(desc) > 100 else "")

        text = (
            f"*{i}. <{url}|{title_romaji}>*"
            + (f"  `{title_native}`" if title_native else "")
            + f"\n⭐ {score}점  |  {status}  |  {episodes}"
            + f"\n🎬 {studio}  |  🏷 {genres}"
            + (f"\n📅 {next_info}" if next_info else "")
            + (f"\n_{desc}_" if desc else "")
        )

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

        if i < len(anime_list):
            blocks.append({"type": "divider"})

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "📡 데이터 출처: <https://anilist.co|AniList> · 봇 자동 발송"}]
    })

    return blocks


def send_slack(blocks: list, text_fallback: str):
    """Slack API로 메시지 전송"""
    payload = json.dumps({
        "channel": SLACK_CHANNEL,
        "text":    text_fallback,
        "blocks":  blocks,
    }).encode()

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data    = payload,
        headers = {
            "Content-Type":  "application/json; charset=utf-8",
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        },
        method  = "POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())

    if not result.get("ok"):
        raise RuntimeError(f"Slack 전송 실패: {result.get('error')}")
    print(f"✅ Slack 전송 성공: {result['ts']}")


def main():
    season, year = get_current_season()
    print(f"📅 분기: {year} {season}")

    anime_list = fetch_anime(season, year, TOP_N)
    print(f"🎌 가져온 애니 수: {len(anime_list)}")

    blocks   = build_slack_blocks(anime_list, season, year)
    fallback = f"{year}년 {season} 분기 신작 애니메이션 TOP {len(anime_list)} 알림"

    send_slack(blocks, fallback)


if __name__ == "__main__":
    main()
