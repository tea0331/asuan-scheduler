#!/usr/bin/env python3
"""
采集排列3历史开奖数据
"""
import requests
import json
import time
from datetime import datetime

def collect_pln_data(limit=100):
    """采集排列3数据"""
    url = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    params = {
        "name": "p3",
        "issueCount": limit
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.cwl.gov.cn/"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10, allow_redirects=True)
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for item in data.get("result", []):
                # 解析开奖号码
                code = item.get("code", "")
                if code:
                    numbers = [int(c) for c in code.split(",") if c.strip()]
                    
                    result = {
                        "lottery": "PLN",
                        "issue": item.get("issue", ""),
                        "date": item.get("date", ""),
                        "numbers": numbers,
                        "sales": int(item.get("sales", 0)),
                        "pool": int(item.get("pool", 0))
                    }
                    results.append(result)
            
            return results
        else:
            print(f"请求失败，状态码: {response.status_code}")
            return []
    except Exception as e:
        print(f"采集排列3数据失败: {e}")
        return []

if __name__ == "__main__":
    print("开始采集排列3数据...")
    data = collect_pln_data(100)
    print(f"采集到 {len(data)} 期数据")
    
    if data:
        # 保存到文件
        output_file = "/root/asuan-scheduler/data-pipeline/raw/PLN.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"数据已保存到 {output_file}")
        
        # 显示前3期数据作为示例
        print("\n前3期数据示例:")
        for item in data[:3]:
            print(json.dumps(item, ensure_ascii=False))
    else:
        print("未采集到数据")
