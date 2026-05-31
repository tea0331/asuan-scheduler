#!/usr/bin/env python3
"""补丁：将_call_hunyuan_api() 从requests换成curl（增加timeout到90秒）"""
import re

with open('generate_full_daily.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到_call_hunyuan_api函数开始和结束的行号
start_line = None
end_line = None
for i, line in enumerate(lines):
    if 'def _call_hunyuan_api' in line:
        start_line = i
    elif start_line is not None and end_line is None and line.startswith('def ') and i > start_line:
        end_line = i
        break

if start_line is None:
    print("❌ 找不到 _call_hunyuan_api 函数")
    exit(1)

print(f"找到函数：行 {start_line+1} 到 {end_line+1}")

# 新函数内容（用curl，timeout=90秒）
new_func = '''def _call_hunyuan_api(system_msg, user_msg, timeout=90):
    """调用混元API，用curl避免requests库卡死问题（timeout=90秒）"""
    import subprocess, json, tempfile, os
    
    api_key = os.getenv('HUNYUAN_API_KEY', 'sk-TjZgBJKZJA1FjrkMHIotwyBafg8gXnRdYBLDvyHNkGSkQAcq')
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": 1000,
        "temperature": 0.75,
    }
    
    # 写入临时JSON文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
        temp_file = f.name
    
    try:
        # 用curl调用（--max-time参数控制超时）
        cmd = [
            'curl', '-s', '-X', 'POST', url,
            '-H', f'Authorization: Bearer {api_key}',
            '-H', 'Content-Type: application/json',
            '--max-time', str(timeout),
            '-d', f'@{temp_file}'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        
        if result.returncode != 0:
            logging.warning(f"[新闻] curl失败: {result.stderr}")
            return None
        
        resp_data = json.loads(result.stdout)
        
        if 'choices' in resp_data and len(resp_data['choices']) > 0:
            content = resp_data['choices'][0]['message']['content']
            content = content.strip()
            # 清理markdown包裹
            if content.startswith('```markdown'):
                content = content[len('```markdown'):]
            if content.startswith('```'):
                content = content[len('```'):]
            if content.endswith('```'):
                content = content[:-3]
            return content.strip()
        elif 'error' in resp_data:
            error_msg = resp_data['error'].get('message', '未知错误')
            logging.warning(f"[新闻] 混元API错误: {error_msg}")
            return None
        else:
            logging.warning(f"[新闻] 混元API返回异常: {result.stdout[:200]}")
            return None
            
    except subprocess.TimeoutExpired:
        logging.warning(f"[新闻] curl超时({timeout}秒)")
        return None
    except Exception as e:
        logging.warning(f"[新闻] 混元API异常: {e}")
        return None
    finally:
        if os.path.exists(temp_file):
            os.unlink(temp_file)

'''

# 替换
new_lines = lines[:start_line] + [new_func] + lines[end_line:]
with open('generate_full_daily.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("✅ 已替换 _call_hunyuan_api() 为curl版本（timeout=90秒）")
print("⚠️  记得删除 import requests（如果存在）")
