# ✅ 阿算答复 — 4个P0缺陷定位 + SSH修复方案

> **答复人**: 阿算  
> **时间**: 2026-06-02 20:35 CST  
> **关联**: 阿策通知_SSH修复_P0缺陷.md (b14a8fa)

---

## 一、4个P0缺陷 — 逐项定位

### P0-1: 死代码 `return result` 残留

| 项目 | 详情 |
|:--|:--|
| **文件** | `jin_zhu.py` |
| **行号** | **L676-677** |
| **问题** | `_gen_ltn()` 方法 L668-674 已有 `return [...]`, L677 的 `return result` 是不可达死代码,且 `result` 未定义 |
| **严重度** | 低(不可达),但污染代码 |

```python
# jin_zhu.py L668-677 (当前)
        return [
            {'front': core_front_A, 'back': core_back_A, ...},
            ...
        ]                          # ← L674: _gen_ltn 在此返回

    # ------ 七星彩推荐 ------      # L676: 异常缩进
        return result               # L677: 死代码,无法执行
```

**修复**: 删除 L676-677。

---

### P0-2: `generate_taiwan.py` 不传递历史数据给 JinZhu

| 项目 | 详情 |
|:--|:--|
| **文件** | `generate_taiwan.py` → `games/pln.py` |
| **行号** | `generate_taiwan.py` L33 → `games/pln.py` L23-27 |
| **问题** | `generate_recs_pln(history)` 把 `history` 当 `analysis` 传入,但 `games/pln.py` 的 `generate_recs_pln` **忽略了这个参数**,调用 `jz.generate_recs('pln', kelly_bias=kelly_bias)` 时没传 `history_data` |
| **后果** | JinZhu 回退到读本地 CSV 文件,无法用实时抓取数据 |

```python
# games/pln.py L23-27 (当前)
def generate_recs_pln(analysis=None, kelly_bias=0.0):
    jz = get_jinzhu()
    return jz.generate_recs('pln', kelly_bias=kelly_bias)  # ← analysis未传递!
```

**修复**: 传 `history_data=analysis` 或重构调用链。

---

### P0-3: `games/ltn.py` 绕过 JinZhu, 使用自研简陋算法

| 项目 | 详情 |
|:--|:--|
| **文件** | `games/ltn.py` |
| **行号** | **L24-61** (`generate_recs_ltn`), **L64-76** (`get_ltn_recommendations`) |
| **问题** | `generate_recs_ltn` L24-61 实现了自己的选号逻辑(top5取前区 + i*2取后区),根本不是 JinZhu 算法 |
| **对比** | `jinzhu.py` L600-674 有正确的 `_gen_ltn()` (Kelly排序+独立池+形态优化+回补+冷号+扰动) |

```python
# games/ltn.py L24-61 (当前 — 非JinZhu算法)
def generate_recs_ltn(analysis, kelly_bias=0.0):
    # 前区: 简单取 front_weights[:5]
    selected = sorted([x[0] for x in front_weights[:5]])
    # 后区: 简单取 back_weights[i*2:(i+1)*2]
    # ← 无Kelly,无独立池,无形态优化,无回补,无扰动
```

**修复**: `get_ltn_recommendations` 应委托给 `jinzhu._gen_ltn()`,与 PLN 保持一致。

---

### P0-4: `_apply_neighbor_bonus` 不支持 PLN/LTN

| 项目 | 详情 |
|:--|:--|
| **文件** | `jin_zhu.py` |
| **行号** | **L250-278** |
| **问题** | 邻号加分只处理 `ssq`(红球±1) 和 `dlt`(前区±1),对 `pln`/`ltn` 直接 `return analysis` 跳过 |
| **影响** | PLN/LTN 预测缺失"球机机械偏差"修正,准确性下降 |

```python
# jin_zhu.py L250-278 (当前)
def _apply_neighbor_bonus(self, game, analysis, history_data):
    if game == 'ssq':
        # 实现邻号加分
    elif game == 'dlt':
        # 实现邻号加分
    # ← pln/ltn 无处理,直接return
    return analysis
```

**修复**: 添加 `pln`(主号6个±1, 1-38) 和 `ltn`(前区5个±1, 1-47) 的邻号加分逻辑。

---

## 二、4个P0缺陷汇总

| # | 缺陷 | 文件:行号 | 严重度 | 预计工时 |
|:--|:--|:--|:--|:--|
| P0-1 | 死代码 `return result` | `jin_zhu.py:676-677` | 🟡 低 | 5分钟 |
| P0-2 | history_data 未传递 | `games/pln.py:27` + `generate_taiwan.py:33` | 🔴 高 | 30分钟 |
| P0-3 | LTN 绕过 JinZhu | `games/ltn.py:24-76` | 🔴 高 | 1小时 |
| P0-4 | 邻号加分缺 PLN/LTN | `jin_zhu.py:250-278` | 🟠 中 | 30分钟 |

---

## 三、SSH 密钥配置

生产服务器 `101.43.44.171` 的 SSH 密钥方案：

```bash
# 方案A: 已有密钥对
# 将私钥放到 ~/.ssh/id_rsa 并设权限
chmod 600 ~/.ssh/id_rsa
ssh -o StrictHostKeyChecking=no ubuntu@101.43.44.171 "hostname"

# 方案B: 生成新密钥对并推送公钥
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
ssh-copy-id ubuntu@101.43.44.171
```

> ⚠️ 当前沙箱环境无访问服务器权限，需你（刘老板）提供私钥或密码。

---

## 四、验收清单

- [ ] `29cf73c` 已 pull — PLN/LTN 推荐报告在 `reports/`
- [ ] P0-1 死代码已删除 (等待你批准后执行)
- [ ] P0-2 history_data 传递链已修复
- [ ] P0-3 LTN 已改走 JinZhu
- [ ] P0-4 邻号加分已支持 PLN/LTN
- [ ] SSH 密钥配置完成

---

> 以上4个P0缺陷定位完毕。等你批准后，我逐项提交修复。SSH 密钥等你从服务器侧提供。
