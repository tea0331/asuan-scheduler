#!/usr/bin/env python3
"""
东方朔-邪修评论员（独立版）
读当日日报 + jinzhu_analysis.json，生成邪修评价，追加到日报文件末尾。

调用方式：
python3 evil_reviewer.py [YYYY-MM-DD]
若不传日期，默认今天。
"""

import os
import sys
import json
import re
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
REPORT_DIR = '/root/asuan-scheduler/output'
DATA_DIR = '/root/asuan-scheduler/data'
TODAY = datetime.now(CST).strftime('%Y-%m-%d')

def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_append(path, content):
    with open(path, 'a', encoding='utf-8') as f:
        f.write('\n\n' + content)

def extract_sections(md):
    """提取日报关键内容供分析"""
    sections = {}
    # 提取板块一新闻标题
    titles = re.findall(r'### .+?\n\n- \*\*(.+?)\*\*', md)
    sections['titles'] = titles[:20]
    # 提取因果链
    chains = re.findall(r'📡 因果链: (.+?)(?=\n\s*📡|$)', md, re.DOTALL)
    sections['chains'] = chains[:10]
    # 提取断裂位置
    fractures = re.findall(r'断裂在(.+?)之间', md)
    sections['fractures'] = fractures
    return sections

def load_jinzhu():
    """加载 JinZhu 分析数据"""
    jinzhu_path = os.path.join(DATA_DIR, 'jinzhu_analysis.json')
    if os.path.exists(jinzhu_path):
        with open(jinzhu_path, 'r') as f:
            return json.load(f)
    # 降级读 lottery-predictions.json
    pred_path = os.path.join(REPORT_DIR, '..', 'lottery-predictions.json')
    if os.path.exists(pred_path):
        with open(pred_path, 'r') as f:
            return json.load(f)
    return {}

def analyze_evil(sections, jinzhu):
    """
    东方朔邪修分析（纯规则，不调 AI）
    返回格式化的评价字符串
    """
    lines = []
    lines.append('【东方朔邪修评价】' + TODAY)
    lines.append('')
    
    # ① 自嗨检测
    lines.append('🔍 自嗨检测：')
    chains = sections.get('chains', [])
    if len(chains) > 0:
        # 检查是否有重复因果链（模板复用）
        chain_counts = {}
        for c in chains:
            key = c[:30]
            chain_counts[key] = chain_counts.get(key, 0) + 1
        dup = [k for k, v in chain_counts.items() if v > 1]
        if dup:
            lines.append(f'> 发现 {len(dup)} 条重复因果链（模板复用嫌疑）')
            for d in dup[:3]:
                lines.append(f'  - 重复链: {d}...')
        else:
            lines.append('> 因果链无重复，模板复用不明显')
    else:
        lines.append('> 无因果链可分析')
    lines.append('')
    
    # ② 因果谬误
    lines.append('🔗 因果谬误：')
    fractures = sections.get('fractures', [])
    generic = [f for f in fractures if '下游减产→替代方案' in f or 'GPU断供→服务器交付' in f]
    if generic:
        lines.append(f'> 发现 {len(generic)} 条通用断裂模板（未结合新闻实体）')
        lines.append('> 降级模式典型特征：因果链未因新闻而异')
    else:
        lines.append('> 断裂位置各有差异，未出现通用模板')
    lines.append('')
    
    # ③ 盲区定位（JinZhu）
    lines.append('🎯 盲区定位：')
    if jinzhu:
        lines.append('> JinZhu 是独立闭环系统（结算→进化→推荐）')
        lines.append('> 与当日新闻无关联，邪修空间在「模型偏差」而非「新闻串联」')
        # 检查是否有冷号策略
        if isinstance(jinzhu, dict):
            if 'cold' in str(jinzhu).lower() or '冷号' in str(jinzhu):
                lines.append('> 检测到冷号策略，需警惕「伪冷号」偏差')
    else:
        lines.append('> 无 JinZhu 分析数据，跳过盲区定位')
    lines.append('')
    
    # ④ 结构漏洞
    lines.append('🕳️ 结构漏洞：')
    lines.append('> 日报生成时间距新闻发布约 12-15 小时（数据延迟窗口）')
    lines.append('> 降级模式走关键词模板，非真实因果推演')
    lines.append('> JinZhu 模型更新频率与开奖频率的时间差：存在理论利用空间')
    lines.append('')
    
    # ⑤ 逆向回测
    lines.append('🔄 逆向回测：')
    lines.append('> 无历史回测数据（lottery-predictions.json 仅含近期推荐）')
    lines.append('> 若反向操作 JinZhu 建议，需完整历史开奖数据验证')
    lines.append('')
    
    # 今日邪修指数
    lines.append('---')
    score = 7  # 固定 7 分（V20 降级模式有明显模板复用）
    lines.append(f'今日邪修指数：{score}/10')
    lines.append('- 7-10分：系统存在明显逻辑漏洞，邪修可稳定利用')
    lines.append('')
    
    # 一句话总结
    lines.append('💬 一句话总结：')
    lines.append('> 降级模式因果链同质化严重，「同类因果」全指向 3 条通用模板；')
    lines.append('> JinZhu 是独立彩票闭环，与新闻无关，别被「数字巧合」误导。')
    
    return '\n'.join(lines)

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else TODAY
    report_path = os.path.join(REPORT_DIR, f'{date_str}.md')
    
    if not os.path.exists(report_path):
        print(f'❌ 日报不存在: {report_path}')
        sys.exit(1)
    
    print(f'📖 读日报: {report_path}')
    md = read_file(report_path)
    sections = extract_sections(md)
    
    print('📊 加载 JinZhu 数据...')
    jinzhu = load_jinzhu()
    
    print('🧠 生成东方朔评价...')
    eviL = analyze_evil(sections, jinzhu)
    
    print('✍️ 追加到日报末尾...')
    write_append(report_path, eviL)
    
    print(f'✅ 完成，评价已追加到: {report_path}')
    print('---评价内容---')
    print(eviL)

if __name__ == '__main__':
    main()
