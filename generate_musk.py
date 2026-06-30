#!/usr/bin/env python3
"""
最简单的马斯克推演生成器
直接调用混元 API，生成基于当日新闻的缺口模式分析
"""
import os
import requests
import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime('%Y-%m-%d')

def load_env():
    env = {}
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env

def generate_musk_inference(daily_content):
    """调用混元 API 生成马斯克推演"""
    env = load_env()
    api_key = env.get('HUNYUAN_API_KEY', '')
    url = 'https://api.lkeap.cloud.tencent.com/plan/v3/chat/completions'
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    prompt = f"""请基于以下阿算日报内容，识别有操作空间的缺口模式，生成推演分析。

日报内容（节选）：
{daily_content[:3000]}

要求：
1. 识别3个最有操作空间的缺口模式
2. 每个模式包含：缺口描述、需求方、操作路径、红线位置、可持续原因
3. 输出格式：Markdown，结构化
4. 总字数：800-1200字

输出："""
    
    payload = {
        'model': 'hy3-preview',
        'messages': [
            {'role': 'system', 'content': '你是马斯克系统，专门分析套利缺口模式。'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.3,
        'max_tokens': 2000
    }
    
    try:
        print('📡 调用混元 API...')
        r = requests.post(url, json=payload, headers=headers, timeout=90)
        print(f'   状态码: {r.status_code}')
        if r.status_code != 200:
            print(f'   ❌ API调用失败: {r.text[:200]}')
            return None
        
        result = r.json()
        # 标准 OpenAI 格式
        if 'choices' in result:
            text = result['choices'][0]['message']['content']
        else:
            print(f'   ❌ 未知响应格式: {result}')
            return None
        
        print(f'   ✅ 推演生成成功，长度: {len(text)} 字符')
        return text
    except Exception as e:
        print(f'   ❌ API调用异常: {e}')
        return None

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else TODAY
    report_path = os.path.join('output', f'{date_str}.md')
    
    if not os.path.exists(report_path):
        print(f'❌ 日报不存在: {report_path}')
        return
    
    with open(report_path, 'r', encoding='utf-8') as f:
        daily_content = f.read()
    
    print(f'📊 生成马斯克推演: {date_str}')
    inference = generate_musk_inference(daily_content)
    
    if not inference:
        print('❌ 推演生成失败')
        return
    
    # 追加到日报文件
    with open(report_path, 'a', encoding='utf-8') as f:
        f.write('\n\n---\n\n## 第8维度：马斯克推演法律评估\n\n')
        f.write(inference)
    
    print(f'✅ 已追加马斯克推演到日报: {report_path}')

if __name__ == '__main__':
    import sys
    main()
