#!/usr/bin/env python3
"""
B站评论区社会心态采样
搜索关键词 → 取播放量>10万视频TOP5 → 采评论 → 情绪标注 → 生成报告
"""
import json
import os
import time
import re
import requests
from datetime import datetime
from collections import Counter

# 尝试导入bilibili-api-python
try:
    from bilibili_api import search, video, comment
    from bilibili_api.search import SearchObjectType
    HAS_BILI_API = True
except ImportError:
    HAS_BILI_API = False
    print("[警告] bilibili-api-python 未安装，将使用网页抓取方式")

OUTPUT_DIR = "/root/asuan-scheduler/data/musk/bilibili-comments"
os.makedirs(OUTPUT_DIR, exist_ok=True)

KEYWORDS = ["反诈", "骗局", "套路", "杀猪盘", "灰色产业", "副业", "搞钱", "焦虑", "内卷"]

EMOTION_LABELS = ["焦虑", "愤怒", "嘲讽", "兴奋", "冷漠", "恐惧", "庆幸"]

def search_videos_biliapi(keyword, top_n=5):
    """用 bilibili-api-python 搜索视频"""
    import asyncio
    from bilibili_api.search import search_by_type, SearchObjectType
    
    async def _search():
        result = await search_by_type(keyword, SearchObjectType.VIDEO, order_type=SearchObjectType.VIDEO)
        videos = []
        for v in result.get('result', [])[:top_n*2]:  # 多取几个过滤
            play = v.get('play', 0)
            if play > 100000:
                videos.append({
                    'bvid': v.get('bvid', ''),
                    'title': v.get('title', '').replace('<em class="keyword">', '').replace('</em>', ''),
                    'play': play,
                    'author': v.get('author', ''),
                    'aid': v.get('aid', 0)
                })
            if len(videos) >= top_n:
                break
        return videos
    
    return asyncio.run(_search())

def search_videos_web(keyword, top_n=5):
    """用网页搜索API（无需登录）"""
    videos = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.bilibili.com'
    }
    # 搜索API
    url = 'https://api.bilibili.com/x/web-interface/search/type'
    params = {
        'search_type': 'video',
        'keyword': keyword,
        'order': 'click',  # 按播放量排序
        'pn': 1,
        'ps': 20
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        for item in data.get('data', {}).get('result', []):
            play = item.get('play', 0)
            if play > 100000:
                videos.append({
                    'bvid': item.get('bvid', ''),
                    'title': re.sub(r'<[^>]+>', '', item.get('title', '')),
                    'play': play,
                    'author': item.get('author', ''),
                    'aid': item.get('aid', 0)
                })
            if len(videos) >= top_n:
                break
    except Exception as e:
        print(f"[搜索失败] {keyword}: {e}")
    return videos

def fetch_comments(bvid, top_n=20):
    """获取视频评论（热门评论）"""
    comments = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': f'https://www.bilibili.com/video/{bvid}'
    }
    # 获取aid
    try:
        r = requests.get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}', headers=headers, timeout=10)
        aid = r.json().get('data', {}).get('aid', 0)
        if not aid:
            return comments
        
        # 获取热门评论
        url = f'https://api.bilibili.com/x/v2/reply/main'
        params = {'type': 1, 'oid': aid, 'next': 0, 'mode': 3}  # mode=3 热门排序
        r = requests.get(url, params=params, headers=headers, timeout=15)
        data = r.json()
        replies = data.get('data', {}).get('replies', [])
        if not replies:
            return comments
        
        for reply in replies[:top_n]:
            comments.append({
                'content': reply.get('content', {}).get('message', ''),
                'like': reply.get('like', 0),
                'rcount': reply.get('rcount', 0),  # 回复数
                'member': reply.get('member', {}).get('uname', '')
            })
    except Exception as e:
        print(f"[评论获取失败] {bvid}: {e}")
    return comments

def label_emotion(text, api_key):
    """用 hy3-preview 标注情绪极性"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    prompt = f"""请判断以下B站评论的情绪极性，只能从以下7个标签选1个：
焦虑 / 愤怒 / 嘲讽 / 兴奋 / 冷漠 / 恐惧 / 庆幸

评论内容：「{text[:200]}」

只输出标签，不要其他文字。"""
    try:
        resp = requests.post(
            "https://api.lkeap.cloud.tencent.com/plan/v3/chat/completions",
            headers=headers,
            json={"model": "hy3-preview", "messages": [{"role": "user", "content": prompt}], "max_tokens": 10},
            timeout=15
        )
        label = resp.json()["choices"][0]["message"]["content"].strip()
        # 验证标签合法性
        if label not in EMOTION_LABELS:
            # 尝试模糊匹配
            for valid in EMOTION_LABELS:
                if valid in label:
                    return valid
            return "冷漠"  # 默认
        return label
    except:
        return "冷漠"

def extract_phrases(comments):
    """提取高频话术（简化版）"""
    phrases = []
    for c in comments:
        text = c['content']
        # 提取短句（10-30字）
        sentences = re.split(r'[，。！？；]', text)
        for s in sentences:
            s = s.strip()
            if 10 <= len(s) <= 50 and not s.startswith('http'):
                phrases.append(s)
    # 统计频率
    phrase_counter = Counter(phrases)
    return [p for p, _ in phrase_counter.most_common(10)]

def main():
    # API Key（从环境变量或配置读取）
    API_KEY = os.getenv('HUNYUAN_API_KEY', 'sk-tp-...bA7D')  # 占位，实际用config里的
    
    # 从 openclaw config 读取真实 key
    import subprocess
    try:
        result = subprocess.run(['openclaw', 'config', 'get', 'models.providers.tencenthytokenplan.apiKey'],
                              capture_output=True, text=True)
        if result.returncode == 0:
            API_KEY = result.stdout.strip().strip('"')
    except:
        pass
    
    all_data = {}
    today = datetime.now().strftime('%Y-%m-%d')
    
    for keyword in KEYWORDS:
        print(f"\n[搜索] 关键词: {keyword}")
        videos = search_videos_web(keyword, top_n=5)
        print(f"  找到 {len(videos)} 个播放量>10万的视频")
        
        keyword_data = {
            'keyword': keyword,
            'date': today,
            'videos': []
        }
        
        for v in videos:
            print(f"  [视频] {v['title'][:40]}... 播放:{v['play']}")
            comments = fetch_comments(v['bvid'], top_n=20)
            print(f"    评论数: {len(comments)}")
            
            # 情绪标注（只标注前10条，避免API调用过多）
            labeled = []
            for i, c in enumerate(comments[:10]):
                emotion = label_emotion(c['content'], API_KEY)
                labeled.append({**c, 'emotion': emotion})
                time.sleep(0.5)  # 避免速率限制
            
            # 其余评论不标注
            for c in comments[10:]:
                labeled.append({**c, 'emotion': '未标注'})
            
            keyword_data['videos'].append({
                'bvid': v['bvid'],
                'title': v['title'],
                'play': v['play'],
                'author': v['author'],
                'comments': labeled
            })
            time.sleep(1)
        
        # 保存该关键词数据
        fname = f"{keyword}-{today}.json"
        fpath = os.path.join(OUTPUT_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(keyword_data, f, ensure_ascii=False, indent=2)
        print(f"  已保存: {fpath}")
        all_data[keyword] = keyword_data
        time.sleep(2)
    
    # 生成社会心态报告
    print("\n[生成报告] social-mood-report.json")
    all_emotions = []
    all_phrases = []
    for kw, data in all_data.items():
        for v in data['videos']:
            for c in v['comments']:
                if c.get('emotion') and c['emotion'] != '未标注':
                    all_emotions.append(c['emotion'])
                all_phrases.extend(extract_phrases([c]))
    
    emotion_dist = Counter(all_emotions)
    total = sum(emotion_dist.values()) or 1
    mood_distribution = {k: round(v/total*100, 1) for k, v in emotion_dist.items()}
    
    phrase_counter = Counter(all_phrases)
    top_phrases = [p for p, _ in phrase_counter.most_common(10)]
    
    # 认知盲区（简化：取情绪为恐惧/焦虑的高赞评论）
    blind_spots = []
    for kw, data in all_data.items():
        for v in data['videos']:
            for c in v['comments']:
                if c.get('emotion') in ['恐惧', '焦虑'] and c.get('like', 0) > 50:
                    blind_spots.append(c['content'][:100])
    blind_spots = list(set(blind_spots))[:5]
    
    report = {
        'date': today,
        'mood_distribution': mood_distribution,
        'top_phrases': top_phrases,
        'cognitive_blindspots': blind_spots,
        'summary': f"共采集{len(all_emotions)}条标注评论，主要情绪：{emotion_dist.most_common(3)}"
    }
    
    report_path = "/root/asuan-scheduler/data/musk/social-mood-report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"报告已保存: {report_path}")
    print(f"情绪分布: {mood_distribution}")
    print(f"高频话术TOP10: {top_phrases}")

if __name__ == '__main__':
    main()
