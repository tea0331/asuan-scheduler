#!/usr/bin/env python3
"""
B站评论区社会心态采样 v5
修复：拉取更多评论（按时间排序，拉多页）
"""
import json
import os
import asyncio
import re
from datetime import datetime
from collections import Counter

from bilibili_api import search, comment
from bilibili_api.search import SearchObjectType, OrderVideo
from bilibili_api.comment import get_comments, CommentResourceType, OrderType

OUTPUT_DIR = "/root/asuan-scheduler/data/musk/bilibili-comments"
os.makedirs(OUTPUT_DIR, exist_ok=True)

KEYWORDS = ["反诈", "骗局", "套路", "杀猪盘", "灰色产业", "副业", "搞钱", "焦虑", "内卷"]

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

async def fetch_comments_paged(aid, max_count=50):
    """按时间排序拉多页评论，最多max_count条"""
    comments = []
    page = 1
    while len(comments) < max_count:
        try:
            data = await get_comments(
                oid=aid,
                type_=CommentResourceType.VIDEO,
                order=OrderType.TIME,  # 按时间排序
                page_index=page
            )
            replies = data.get('replies', [])
            if not replies:
                break
            for r in replies:
                content = r.get('content', {}).get('message', '')
                content = re.sub(r'\[at:\d+\]', '', content)
                content = re.sub(r'<[^>]+>', '', content)
                comments.append({
                    'content': content,
                    'like': r.get('like', {}).get('count', 0) if isinstance(r.get('like'), dict) else r.get('like', 0),
                    'rcount': r.get('rcount', 0),
                    'member': r.get('member', {}).get('uname', ''),
                    'rpid': r.get('rpid', 0)
                })
                if len(comments) >= max_count:
                    break
            page += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"    [评论页{page}失败] aid={aid}: {e}")
            break
    return comments

async def main():
    print("=== B站评论区社会心态采样 v5 ===")
    today = datetime.now().strftime('%Y-%m-%d')
    
    for keyword in KEYWORDS:
        print(f"\n[关键词] {keyword}")
        videos = await search_videos(keyword, top_n=5)
        print(f"  找到 {len(videos)} 个播放量>10万的视频")
        
        keyword_data = {
            'keyword': keyword,
            'date': today,
            'videos': []
        }
        
        for v in videos:
            print(f"  [视频] {v['title'][:40]}... 播放:{v['play']}")
            comments = await fetch_comments_paged(v['aid'], max_count=50)
            print(f"    评论数: {len(comments)}")
            
            v_data = {**v, 'comments': comments}
            keyword_data['videos'].append(v_data)
            await asyncio.sleep(1)
        
        fname = f"{keyword}-{today}.json"
        fpath = os.path.join(OUTPUT_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(keyword_data, f, ensure_ascii=False, indent=2)
        print(f"  已保存: {fname}")
        await asyncio.sleep(2)
    
    print("\n=== 评论数据采集完成 ===")

if __name__ == '__main__':
    asyncio.run(main())
