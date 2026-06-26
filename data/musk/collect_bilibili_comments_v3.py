#!/usr/bin/env python3
"""
B站评论区社会心态采样 v3
修复：正确使用 bilibili-api-python 的 comment 模块
"""
import json
import os
import time
import asyncio
import re
from datetime import datetime
from collections import Counter

from bilibili_api import search, comment, video
from bilibili_api.search import SearchObjectType, OrderVideo
from bilibili_api.comment import get_comments, CommentResourceType, OrderType

OUTPUT_DIR = "/root/asuan-scheduler/data/musk/bilibili-comments"
os.makedirs(OUTPUT_DIR, exist_ok=True)

KEYWORDS = ["反诈", "骗局", "套路", "杀猪盘", "灰色产业", "副业", "搞钱", "焦虑", "内卷"]

EMOTION_LABELS = ["焦虑", "愤怒", "嘲讽", "兴奋", "冷漠", "恐惧", "庆幸"]

# 获取 API Key
import subprocess
def get_api_key():
    try:
        r = subprocess.run(['openclaw', 'config', 'get', 'models.providers.tencenthytokenplan.apiKey'],
                          capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip().strip('"')
    except:
        pass
    return os.getenv('HUNYUAN_API_KEY', '')

API_KEY = get_api_key()
API_URL = "https://api.lkeap.cloud.tencent.com/plan/v3"

async def search_videos(keyword, top_n=5, min_play=100000):
    """搜索播放量>min_play的视频TOP5"""
    result = await search.search_by_type(
        keyword=keyword,
        search_type=SearchObjectType.VIDEO,
        order_type=OrderVideo.CLICK,
        page=1,
        page_size=20
    )
    videos = []
    for v in result.get('result', []):
        play = v.get('play', 0)
        if play >= min_play:
            title = re.sub(r'<[^>]+>', '', v.get('title', ''))
            videos.append({
                'bvid': v.get('bvid', ''),
                'aid': v.get('aid', 0),
                'title': title,
                'play': play,
                'author': v.get('author', ''),
                'duration': v.get('duration', 0)
            })
        if len(videos) >= top_n:
            break
    return videos

async def fetch_comments(bvid, aid, top_n=20):
    """获取视频热门评论TOP n（按点赞数排序）"""
    try:
        comments_data = await get_comments(
            oid=aid,
            type_=CommentResourceType.VIDEO,
            order=OrderType.LIKE,
            page_index=1
        )
        replies = comments_data.get('replies', [])[:top_n]
        comments = []
        for r in replies:
            content = r.get('content', {}).get('message', '')
            # 清理内容
            content = re.sub(r'\[at:\d+\]', '', content)
            content = re.sub(r'<[^>]+>', '', content)
            comments.append({
                'content': content,
                'like': r.get('like', {}).get('count', 0) if isinstance(r.get('like'), dict) else r.get('like', 0),
                'rcount': r.get('rcount', 0),
                'member': r.get('member', {}).get('uname', ''),
                'rpid': r.get('rpid', 0)
            })
        return comments
    except Exception as e:
        print(f"    [评论获取失败] {bvid}: {e}")
        return []

def label_emotion(text):
    """用 hy3-preview 标注情绪极性"""
    if not API_KEY:
        return "冷漠"
    import requests
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"""请判断以下B站评论的情绪极性，只能从以下7个标签选1个：
焦虑 / 愤怒 / 嘲讽 / 兴奋 / 冷漠 / 恐惧 / 庆幸

评论内容：「{text[:200]}」

只输出标签，不要其他文字。"""
    try:
        resp = requests.post(
            f"{API_URL}/chat/completions",
            headers=headers,
            json={"model": "hy3-preview", "messages": [{"role": "user", "content": prompt}], "max_tokens": 10, "temperature": 0.3},
            timeout=15
        )
        label = resp.json()["choices"][0]["message"]["content"].strip()
        for valid in EMOTION_LABELS:
            if valid in label:
                return valid
        return "冷漠"
    except Exception as e:
        print(f"    [情绪标注失败] {e}")
        return "冷漠"

def extract_phrases(all_comments):
    """提取高频话术TOP10"""
    phrases = []
    for c in all_comments:
        text = c.get('content', '')
        sentences = re.split(r'[，。！？；\n]', text)
        for s in sentences:
            s = s.strip()
            if 8 <= len(s) <= 60 and not s.startswith('http'):
                phrases.append(s)
    phrase_counter = Counter(phrases)
    return [p for p, _ in phrase_counter.most_common(10)]

async def process_keyword(keyword):
    """处理单个关键词"""
    print(f"\n[关键词] {keyword}")
    videos = await search_videos(keyword, top_n=5)
    print(f"  找到 {len(videos)} 个播放量>10万的视频")

    keyword_data = {
        'keyword': keyword,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'videos': []
    }

    all_comments_for_keyword = []
    for v in videos:
        print(f"  [视频] {v['title'][:40]}... 播放:{v['play']}")
        comments = await fetch_comments(v['bvid'], v['aid'], top_n=20)
        print(f"    评论数: {len(comments)}")

        labeled = []
        for i, c in enumerate(comments):
            emotion = label_emotion(c['content'])
            labeled.append({**c, 'emotion': emotion})
            if (i+1) % 5 == 0:
                print(f"      已标注 {i+1}/{len(comments)}")
            time.sleep(0.3)

        v_data = {**v, 'comments': labeled}
        keyword_data['videos'].append(v_data)
        all_comments_for_keyword.extend(labeled)
        await asyncio.sleep(1)

    # 保存该关键词数据
    today = datetime.now().strftime('%Y-%m-%d')
    fname = f"{keyword}-{today}.json"
    fpath = os.path.join(OUTPUT_DIR, fname)
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(keyword_data, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {fname}")

    return keyword_data, all_comments_for_keyword

async def main():
    print("=== B站评论区社会心态采样 ===")
    print(f"关键词数: {len(KEYWORDS)}")
    print(f"API Key: {'已配置' if API_KEY else '未配置（情绪标注将使用默认）'}")

    all_keyword_data = {}
    all_comments = []

    for keyword in KEYWORDS:
        kd, comments = await process_keyword(keyword)
        all_keyword_data[keyword] = kd
        all_comments.extend(comments)
        await asyncio.sleep(2)

    # 生成社会心态报告
    print("\n[生成报告] social-mood-report.json")
    all_emotions = [c['emotion'] for c in all_comments if c.get('emotion') and c['emotion'] != '未标注']
    emotion_dist = Counter(all_emotions)
    total = sum(emotion_dist.values()) or 1
    mood_distribution = {k: round(v/total*100, 1) for k, v in emotion_dist.items()}

    top_phrases = extract_phrases(all_comments)

    # 认知盲区 (恐惧/焦虑的高赞评论)
    blind_spots = []
    for c in all_comments:
        if c.get('emotion') in ['恐惧', '焦虑'] and c.get('like', 0) > 30:
            txt = c['content'][:120].strip()
            if txt and txt not in blind_spots:
                blind_spots.append(txt)
    blind_spots = blind_spots[:5]

    report = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'total_comments_labeled': len(all_emotions),
        'mood_distribution': mood_distribution,
        'top_phrases': top_phrases,
        'cognitive_blindspots': blind_spots,
        'summary': f"共采集标注{len(all_emotions)}条评论，主要情绪分布: {dict(emotion_dist.most_common(3))}"
    }

    report_path = "/root/asuan-scheduler/data/musk/social-mood-report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=== 完成 ===")
    print(f"报告已保存: {report_path}")
    print(f"情绪分布: {mood_distribution}")
    print(f"高频话术TOP10:")
    for i, p in enumerate(top_phrases, 1):
        print(f"  {i}. {p}")
    if blind_spots:
        print(f"认知盲区TOP5:")
        for i, b in enumerate(blind_spots, 1):
            print(f"  {i}. {b[:80]}...")

if __name__ == '__main__':
    asyncio.run(main())
