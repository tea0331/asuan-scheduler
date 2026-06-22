#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双色球(SSQ)和大乐透(DLT)历史开奖数据采集脚本
采集最近100期历史数据并保存为JSON格式
"""

import requests
import json
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup

def fetch_ssq_data(count=100):
    """采集双色球历史数据"""
    print(f"开始采集双色球最近{count}期数据...")
    url = f"http://datachart.500star.com/ssq/history/history.shtml"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = 'gb2312'
        html = resp.text
        
        # 使用正则表达式提取数据
        # 匹配模式：期号 红球1-6 蓝球 奖池 一等奖注数 一等奖金额 二等奖注数 二等奖金额 销售额 日期
        pattern = r'(\d{5,6})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+(\d{4}-\d{2}-\d{2})'
        
        # 尝试更灵活的正则
        pattern2 = r'(\d{5,6})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+(\d{1,2}-\d{1,2}-\d{1,2})'
        
        matches = re.findall(pattern2, html)
        
        if not matches:
            # 尝试使用BeautifulSoup解析表格
            soup = BeautifulSoup(html, 'html.parser')
            table = soup.find('table', class_='history')
            if not table:
                table = soup.find_all('table')[1] if len(soup.find_all('table')) > 1 else None
            
            if table:
                rows = table.find_all('tr')
                data_list = []
                for row in rows[1:]:  # 跳过表头
                    cols = row.find_all('td')
                    if len(cols) >= 10:
                        try:
                            issue = cols[0].text.strip()
                            red_balls = [int(cols[i].text.strip()) for i in range(1, 7)]
                            blue_ball = int(cols[7].text.strip())
                            pool = cols[8].text.strip().replace(',', '')
                            sales = cols[9].text.strip().replace(',', '')
                            date = cols[10].text.strip() if len(cols) > 10 else ''
                            
                            numbers = red_balls + [blue_ball]
                            data_list.append({
                                'lottery': 'SSQ',
                                'issue': issue,
                                'date': date,
                                'numbers': numbers,
                                'sales': int(sales) if sales.isdigit() else 0,
                                'pool': int(pool) if pool.isdigit() else 0
                            })
                        except Exception as e:
                            print(f"解析行出错: {e}")
                            continue
                
                if data_list:
                    return data_list[:count]
        
        # 如果正则匹配成功
        data_list = []
        for match in matches[:count]:
            try:
                issue = match[0]
                numbers = [int(match[i]) for i in range(1, 8)]
                pool = match[8].replace(',', '')
                sales = match[12].replace(',', '')
                date = match[13]
                
                data_list.append({
                    'lottery': 'SSQ',
                    'issue': issue,
                    'date': date,
                    'numbers': numbers,
                    'sales': int(sales) if sales.isdigit() else 0,
                    'pool': int(pool) if pool.isdigit() else 0
                })
            except Exception as e:
                print(f"处理数据出错: {e}")
                continue
        
        if data_list:
            return data_list
        else:
            print("未能解析到数据，尝试直接提取页面文本...")
            # 最后的尝试：直接搜索数字模式
            return extract_ssq_fallback(html, count)
            
    except Exception as e:
        print(f"采集双色球数据失败: {e}")
        return []

def extract_ssq_fallback(html, count):
    """备用提取方法"""
    # 查找所有符合条件的期号和数据
    pattern = r'(\d{5})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})'
    matches = re.findall(pattern, html)
    
    data_list = []
    for match in matches[:count]:
        try:
            issue = f"20{match[0]}"  # 假设是2020年后的数据
            numbers = [int(x) for x in match[1:]]
            data_list.append({
                'lottery': 'SSQ',
                'issue': issue,
                'date': '',
                'numbers': numbers,
                'sales': 0,
                'pool': 0
            })
        except:
            continue
    
    return data_list

def fetch_dlt_data(count=100):
    """采集大乐透历史数据"""
    print(f"开始采集大乐透最近{count}期数据...")
    url = f"http://datachart.500star.com/dlt/history/history.shtml"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = 'gb2312'
        html = resp.text
        
        # 使用BeautifulSoup解析
        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.find_all('table')
        
        data_list = []
        if len(tables) > 1:
            table = tables[1]  # 第二个表格通常是数据表格
            rows = table.find_all('tr')
            
            for row in rows[1:]:  # 跳过表头
                cols = row.find_all('td')
                if len(cols) >= 10:
                    try:
                        issue = cols[0].text.strip()
                        # 前区5个球
                        front_balls = []
                        for i in range(1, 6):
                            ball = cols[i].text.strip()
                            if ball.isdigit():
                                front_balls.append(int(ball))
                        
                        # 后区2个球
                        back_balls = []
                        for i in range(6, 8):
                            ball = cols[i].text.strip()
                            if ball.isdigit():
                                back_balls.append(int(ball))
                        
                        if len(front_balls) == 5 and len(back_balls) == 2:
                            numbers = front_balls + back_balls
                            pool = cols[8].text.strip().replace(',', '') if len(cols) > 8 else '0'
                            sales = cols[9].text.strip().replace(',', '') if len(cols) > 9 else '0'
                            date = cols[10].text.strip() if len(cols) > 10 else ''
                            
                            data_list.append({
                                'lottery': 'DLT',
                                'issue': issue,
                                'date': date,
                                'numbers': numbers,
                                'sales': int(sales) if sales.isdigit() else 0,
                                'pool': int(pool) if pool.isdigit() else 0
                            })
                    except Exception as e:
                        print(f"解析大乐透行出错: {e}")
                        continue
        
        if data_list:
            return data_list[:count]
        else:
            print("未能通过表格解析大乐透数据，尝试正则...")
            return extract_dlt_fallback(html, count)
            
    except Exception as e:
        print(f"采集大乐透数据失败: {e}")
        return []

def extract_dlt_fallback(html, count):
    """大乐透备用提取方法"""
    # 查找期号和前5后2的模式
    pattern = r'(\d{5})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})'
    matches = re.findall(pattern, html)
    
    data_list = []
    for match in matches[:count]:
        try:
            issue = f"20{match[0]}"
            numbers = [int(x) for x in match[1:]]
            data_list.append({
                'lottery': 'DLT',
                'issue': issue,
                'date': '',
                'numbers': numbers,
                'sales': 0,
                'pool': 0
            })
        except:
            continue
    
    return data_list

def save_to_json(data, filepath):
    """保存数据到JSON文件"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"数据已保存到: {filepath}")
        return True
    except Exception as e:
        print(f"保存文件失败: {e}")
        return False

def main():
    # 创建输出目录
    output_dir = '/root/asuan-scheduler/data-pipeline/raw'
    
    # 采集双色球数据
    ssq_data = fetch_ssq_data(100)
    if ssq_data:
        ssq_path = f"{output_dir}/SSQ.json"
        save_to_json(ssq_data, ssq_path)
        print(f"双色球数据采集完成，共{len(ssq_data)}期")
        print(f"最新一期: {ssq_data[0]['issue']} ({ssq_data[0]['date']})")
        print(f"最老一期: {ssq_data[-1]['issue']} ({ssq_data[-1]['date']})")
    else:
        print("双色球数据采集失败")
    
    # 等待一下避免请求过快
    time.sleep(2)
    
    # 采集大乐透数据
    dlt_data = fetch_dlt_data(100)
    if dlt_data:
        dlt_path = f"{output_dir}/DLT.json"
        save_to_json(dlt_data, dlt_path)
        print(f"大乐透数据采集完成，共{len(dlt_data)}期")
        print(f"最新一期: {dlt_data[0]['issue']} ({dlt_data[0]['date']})")
        print(f"最老一期: {dlt_data[-1]['issue']} ({dlt_data[-1]['date']})")
    else:
        print("大乐透数据采集失败")
    
    # Git commit
    import subprocess
    try:
        subprocess.run(['git', 'add', 'data-pipeline/raw/'], cwd='/root/asuan-scheduler', check=True)
        subprocess.run(['git', 'commit', '-m', 'data: 采集SSQ/DLT原始数据 (阶段一-子AgentA)'], 
                      cwd='/root/asuan-scheduler', check=True)
        print("Git commit 完成")
    except Exception as e:
        print(f"Git commit 失败: {e}")

if __name__ == '__main__':
    main()
