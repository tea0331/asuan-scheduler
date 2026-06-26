#!/usr/bin/env python3
"""
B站评论区社会心态采样 v4
只拉评论数据，不调外部API做情绪标注
情绪标注由阿策（hy3-preview）后续处理
"""
import json
import os
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

async def fetch_comments(aid, top_n=30):
    """获取视频评论TOP n（按点赞数排序）"""
    try:
        # 按点赞数排序
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
        print(f"    [评论获取失败] aid={aid}: {e}")
        return []

async def main():
    print("=== B站评论区社会心态采样 ===")
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
            comments = await fetch_comments(v['aid'], top_n=30)
            print(f"    评论数: {len(comments)}")
            
            v_data = {**v, 'comments': comments}
            keyword_data['videos'].append(v_data)
            await asyncio.sleep(1)
        
        # 保存该关键词数据
        fname = f"{keyword}-{today}.json"
        fpath = os.path.join(OUTPUT_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(keyword_data, f, ensure_ascii=False, indent=2)
        print(f"  已保存: {fname}")
        await asyncio.sleep(2)
    
    print("\n=== 评论数据采集完成 ===")
    print(f"数据目录: {OUTPUT_DIR}")

if __name__ == '__main__':
    asyncio.run(main())
