#!/usr/bin/env python3
"""
刘海蟾点金 - 统一算法引擎 v3.0
GEPA权重进化 + 策略权重自适应 + 组合投注优化 + ROI追踪 + 自动进化

统一入口: AlgoEngine
  - evolve()  → GEPA P0进化 + 策略权重 + 策略发现 + 模拟退火
  - optimize() → 组合优化
  - settle()  → 结算昨日
  - daily_update() → 完整每日流程

数据存储: algo_state.db (SQLite 8张表, 主) + weight-config.json (从, 兼容WeightedAnalyzer)
"""

import os
import sys
import json
import math
import random
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

# 模块目录
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(MODULE_DIR, 'algo_state.db')
WEIGHT_CONFIG_FILE = os.path.join(MODULE_DIR, 'weight-config.json')

# CST时区
CST_OFFSET = timedelta(hours=8)


def _now_cst():
    return datetime.utcnow() + CST_OFFSET


# ===== 默认P0权重配置 =====

DEFAULT_WEIGHT_CONFIG = {
    'freq': 0.30, 'miss': 0.25, 'trend': 0.25, 'zone': 0.20,
    'cold_miss_front': 0.40, 'cold_cycle_front': 0.30, 'cold_freq_front': 0.30,
    'cold_miss_back': 0.30, 'cold_cycle_back': 0.40, 'cold_freq_back': 0.30,
    'neighbor_bonus': 0.03, 'gamma': 0.88,
    'version': 1, 'algo_version': 'v3.0', 'evolution_log': [],
}

ALL_PARAM_KEYS = [
    'freq', 'miss', 'trend', 'zone',
    'cold_miss_front', 'cold_cycle_front', 'cold_freq_front',
    'cold_miss_back', 'cold_cycle_back', 'cold_freq_back',
    'neighbor_bonus', 'gamma',
]


# ===== 策略定义 =====

class StrategyProfile:
    """策略配置常量"""
    P0_CORE = {'key': 'P0_CORE', 'name': 'P0核心注', 'bias': 'hot', 'kelly_mult': 1.0, 'source': 'existing'}
    P1_AGGRESSIVE = {'key': 'P1_AGGRESSIVE', 'name': 'P1激进注', 'bias': 'hot', 'kelly_mult': 1.5, 'source': 'algo'}
    P2_RECOVERY = {'key': 'P2_RECOVERY', 'name': 'P2回补注', 'bias': 'cold', 'kelly_mult': 0.8, 'source': 'algo'}
    P3_BALANCED = {'key': 'P3_BALANCED', 'name': 'P3均衡注', 'bias': 'balanced', 'kelly_mult': 1.0, 'source': 'algo'}
    P4_MARKOV = {'key': 'P4_MARKOV', 'name': 'P4转移注', 'bias': 'transition', 'kelly_mult': 1.0, 'source': 'markov'}
    P5_BAYESIAN = {'key': 'P5_BAYESIAN', 'name': 'P5贝叶斯注', 'bias': 'bayesian', 'kelly_mult': 1.0, 'source': 'bayesian'}

    ALL = [P0_CORE, P1_AGGRESSIVE, P2_RECOVERY, P3_BALANCED, P4_MARKOV, P5_BAYESIAN]

    @classmethod
    def get(cls, key):
        for s in cls.ALL:
            if s['key'] == key:
                return s
        return None

    @classmethod
    def add_custom(cls, profile):
        """添加自定义策略"""
        cls.ALL.append(profile)


# ===== 数据持久化层 =====

class AlgoDB:
    """SQLite数据持久化 — 8张表"""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._init_tables()
        self._migrate_weight_config()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        conn = self._get_conn()
        c = conn.cursor()

        # 原有5张表
        c.execute('''CREATE TABLE IF NOT EXISTS algo_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL DEFAULT 'default',
            date TEXT NOT NULL, game TEXT NOT NULL, strategy TEXT NOT NULL,
            numbers TEXT NOT NULL, cost INTEGER NOT NULL DEFAULT 2,
            kelly_weight REAL NOT NULL DEFAULT 0, ev_estimate REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL)''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bet_id INTEGER NOT NULL REFERENCES algo_bets(id),
            user_id TEXT NOT NULL DEFAULT 'default', actual_numbers TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0, prize_tier INTEGER NOT NULL DEFAULT 0,
            prize_name TEXT NOT NULL DEFAULT '未中奖', prize_amount INTEGER NOT NULL DEFAULT 0,
            settled_at TEXT NOT NULL)''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_roi_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'default', game TEXT NOT NULL,
            total_cost INTEGER NOT NULL DEFAULT 0, total_prize INTEGER NOT NULL DEFAULT 0,
            roi REAL NOT NULL DEFAULT 0, hit_rate REAL NOT NULL DEFAULT 0,
            avg_hit_count REAL NOT NULL DEFAULT 0, bet_count INTEGER NOT NULL DEFAULT 0,
            strategy_breakdown TEXT DEFAULT '{}', UNIQUE(date, user_id, game))''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_strategy_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            strategy_name TEXT NOT NULL, game TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 0.25, roi_7d REAL NOT NULL DEFAULT 0,
            roi_30d REAL NOT NULL DEFAULT 0, hit_rate_7d REAL NOT NULL DEFAULT 0,
            sample_count INTEGER NOT NULL DEFAULT 0, last_updated TEXT NOT NULL,
            UNIQUE(date, strategy_name, game))''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_params (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            params TEXT NOT NULL, performance TEXT DEFAULT '{}', UNIQUE(date))''')

        # 新增3张表
        c.execute('''CREATE TABLE IF NOT EXISTS algo_gepa_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            game TEXT NOT NULL DEFAULT 'all', version INTEGER NOT NULL DEFAULT 1,
            algo_version TEXT NOT NULL DEFAULT 'v3.0',
            weights TEXT NOT NULL DEFAULT '{}', lock_config TEXT NOT NULL DEFAULT '{}',
            evolution_log TEXT NOT NULL DEFAULT '[]', ai_avg_hit REAL NOT NULL DEFAULT 0,
            step_size REAL NOT NULL DEFAULT 0.02, is_major INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, UNIQUE(date, game))''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_discovered_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_key TEXT NOT NULL UNIQUE,
            strategy_name TEXT NOT NULL, base_strategy TEXT NOT NULL,
            bias TEXT NOT NULL DEFAULT 'custom', kelly_mult REAL NOT NULL DEFAULT 1.0,
            tweak_params TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL DEFAULT 'discovered',
            roi_7d REAL NOT NULL DEFAULT 0, hit_rate_7d REAL NOT NULL DEFAULT 0,
            sample_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
            discovered_at TEXT NOT NULL, retired_at TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_anneal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            game TEXT NOT NULL DEFAULT 'all', temperature REAL NOT NULL DEFAULT 1.0,
            old_weights TEXT NOT NULL, new_weights TEXT NOT NULL,
            old_score REAL NOT NULL DEFAULT 0, new_score REAL NOT NULL DEFAULT 0,
            accepted INTEGER NOT NULL DEFAULT 0, UNIQUE(date, game))''')

        # algo_strategy_state 新增列
        try:
            c.execute('ALTER TABLE algo_strategy_state ADD COLUMN source TEXT NOT NULL DEFAULT \'predefined\'')
        except sqlite3.OperationalError:
            pass  # 列已存在

        # v3.0新增表
        c.execute('''CREATE TABLE IF NOT EXISTS algo_bayesian_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            alpha_json TEXT NOT NULL DEFAULT '{}',
            beta_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            UNIQUE(game))''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_markov_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            transition_json TEXT NOT NULL DEFAULT '{}',
            current_state_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            UNIQUE(game))''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_stacking_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            meta_weights_json TEXT NOT NULL DEFAULT '{}',
            fitted_at TEXT NOT NULL,
            UNIQUE(game))''')

        c.execute('''CREATE TABLE IF NOT EXISTS algo_orchestrator_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            context TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(date))''')

        conn.commit()
        conn.close()

    def _migrate_weight_config(self):
        """首次启动：从weight-config.json迁移P0权重到algo_gepa_state"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM algo_gepa_state')
        count = c.fetchone()[0]
        conn.close()

        if count > 0:
            return  # 已有数据，不需要迁移

        # 从weight-config.json读取
        try:
            with open(WEIGHT_CONFIG_FILE, 'r') as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            config = dict(DEFAULT_WEIGHT_CONFIG)

        # 移除gepa_locked
        config.pop('gepa_locked', None)

        # 写入algo_gepa_state
        today = _now_cst().strftime('%Y-%m-%d')
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''INSERT OR IGNORE INTO algo_gepa_state
                     (date, game, version, algo_version, weights, lock_config, evolution_log,
                      ai_avg_hit, step_size, is_major, created_at)
                     VALUES (?, 'all', ?, ?, ?, '{}', ?, 0, 0.02, 0, ?)''',
                  (today,
                   config.get('version', 1),
                   config.get('algo_version', 'v3.0'),
                   json.dumps({k: config.get(k, DEFAULT_WEIGHT_CONFIG.get(k, 0)) for k in ALL_PARAM_KEYS}, ensure_ascii=False),
                   json.dumps(config.get('evolution_log', []), ensure_ascii=False),
                   _now_cst().isoformat()))
        conn.commit()
        conn.close()
        print(f"[AlgoDB] 已迁移weight-config.json → algo_gepa_state")

    # --- GEPA状态 ---

    def get_latest_gepa_state(self):
        """获取最新GEPA状态"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM algo_gepa_state ORDER BY date DESC, id DESC LIMIT 1')
        row = c.fetchone()
        conn.close()
        if row:
            result = dict(row)
            result['weights'] = json.loads(result.get('weights', '{}'))
            result['lock_config'] = json.loads(result.get('lock_config', '{}'))
            result['evolution_log'] = json.loads(result.get('evolution_log', '[]'))
            return result
        return None

    def save_gepa_state(self, date, config, ai_avg_hit=0, step_size=0.02, is_major=False):
        """保存GEPA状态"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO algo_gepa_state
                     (date, game, version, algo_version, weights, lock_config, evolution_log,
                      ai_avg_hit, step_size, is_major, created_at)
                     VALUES (?, 'all', ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (date,
                   config.get('version', 1),
                   config.get('algo_version', 'v3.0'),
                   json.dumps({k: config.get(k, 0) for k in ALL_PARAM_KEYS}, ensure_ascii=False),
                   json.dumps(config.get('lock_config', {}), ensure_ascii=False),
                   json.dumps(config.get('evolution_log', []), ensure_ascii=False),
                   ai_avg_hit, step_size, 1 if is_major else 0,
                   _now_cst().isoformat()))
        conn.commit()
        conn.close()

    # --- 下注/结算/ROI/策略状态/参数 (原有方法) ---

    def save_bet(self, user_id, date, game, strategy, numbers, cost=2, kelly_weight=0, ev_estimate=0):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''INSERT INTO algo_bets (user_id, date, game, strategy, numbers, cost, kelly_weight, ev_estimate, status, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)''',
                  (user_id, date, game, strategy, json.dumps(numbers, ensure_ascii=False),
                   cost, kelly_weight, ev_estimate, _now_cst().isoformat()))
        bet_id = c.lastrowid
        conn.commit()
        conn.close()
        return bet_id

    def get_pending_bets(self, date=None, game=None):
        conn = self._get_conn()
        c = conn.cursor()
        sql = 'SELECT * FROM algo_bets WHERE status = ?'
        params = ['pending']
        if date:
            sql += ' AND date = ?'
            params.append(date)
        if game:
            sql += ' AND game = ?'
            params.append(game)
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def settle_bet(self, bet_id, actual_numbers, hit_count, prize_tier, prize_name, prize_amount, user_id='default'):
        conn = self._get_conn()
        c = conn.cursor()
        now = _now_cst().isoformat()
        c.execute('''INSERT INTO algo_settlements (bet_id, user_id, actual_numbers, hit_count, prize_tier, prize_name, prize_amount, settled_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (bet_id, user_id, json.dumps(actual_numbers, ensure_ascii=False),
                   hit_count, prize_tier, prize_name, prize_amount, now))
        c.execute('UPDATE algo_bets SET status = ? WHERE id = ?', ('settled', bet_id))
        conn.commit()
        conn.close()

    def get_settled_bets(self, date, game=None, user_id=None):
        conn = self._get_conn()
        c = conn.cursor()
        sql = '''SELECT b.*, s.hit_count, s.prize_tier, s.prize_name, s.prize_amount
                 FROM algo_bets b JOIN algo_settlements s ON b.id = s.bet_id
                 WHERE b.date = ? AND b.status = 'settled' '''
        params = [date]
        if game:
            sql += ' AND b.game = ?'
            params.append(game)
        if user_id:
            sql += ' AND b.user_id = ?'
            params.append(user_id)
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def save_roi_daily(self, date, user_id, game, total_cost, total_prize, roi, hit_rate, avg_hit_count, bet_count, strategy_breakdown=None):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO algo_roi_daily
                     (date, user_id, game, total_cost, total_prize, roi, hit_rate, avg_hit_count, bet_count, strategy_breakdown)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (date, user_id, game, total_cost, total_prize, roi, hit_rate, avg_hit_count, bet_count,
                   json.dumps(strategy_breakdown or {}, ensure_ascii=False)))
        conn.commit()
        conn.close()

    def get_roi_history(self, game, days=7, user_id='default'):
        conn = self._get_conn()
        c = conn.cursor()
        end_date = _now_cst().strftime('%Y-%m-%d')
        start_date = (_now_cst() - timedelta(days=days)).strftime('%Y-%m-%d')
        c.execute('''SELECT * FROM algo_roi_daily
                     WHERE game = ? AND user_id = ? AND date >= ? AND date <= ?
                     ORDER BY date DESC''', (game, user_id, start_date, end_date))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def save_strategy_state(self, date, strategy_name, game, weight, roi_7d=0, roi_30d=0, hit_rate_7d=0, sample_count=0):
        conn = self._get_conn()
        c = conn.cursor()
        now = _now_cst().isoformat()
        c.execute('''INSERT OR REPLACE INTO algo_strategy_state
                     (date, strategy_name, game, weight, roi_7d, roi_30d, hit_rate_7d, sample_count, last_updated)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (date, strategy_name, game, weight, roi_7d, roi_30d, hit_rate_7d, sample_count, now))
        conn.commit()
        conn.close()

    def get_latest_strategy_states(self, game):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''SELECT s.* FROM algo_strategy_state s
                     INNER JOIN (
                         SELECT strategy_name, MAX(date) as max_date
                         FROM algo_strategy_state WHERE game = ?
                         GROUP BY strategy_name
                     ) m ON s.strategy_name = m.strategy_name AND s.date = m.max_date AND s.game = ?
                     ORDER BY s.strategy_name''', (game, game))
        rows = c.fetchall()
        conn.close()
        return {r['strategy_name']: dict(r) for r in rows}

    def get_strategy_roi(self, strategy_name, game, days=7):
        conn = self._get_conn()
        c = conn.cursor()
        end_date = _now_cst().strftime('%Y-%m-%d')
        start_date = (_now_cst() - timedelta(days=days)).strftime('%Y-%m-%d')
        c.execute('''SELECT b.strategy, SUM(s.prize_amount) as total_prize, SUM(b.cost) as total_cost,
                     COUNT(*) as total_bets, SUM(CASE WHEN s.prize_tier > 0 THEN 1 ELSE 0 END) as hit_bets,
                     SUM(s.hit_count) as total_hits
                     FROM algo_bets b JOIN algo_settlements s ON b.id = s.bet_id
                     WHERE b.strategy = ? AND b.game = ? AND b.date >= ? AND b.date <= ? AND b.status = 'settled'
                     GROUP BY b.strategy''',
                  (strategy_name, game, start_date, end_date))
        row = c.fetchone()
        conn.close()
        if row and row['total_bets'] > 0:
            return {
                'roi': row['total_prize'] / row['total_cost'] if row['total_cost'] > 0 else 0,
                'hit_rate': row['hit_bets'] / row['total_bets'],
                'avg_hits': row['total_hits'] / row['total_bets'],
                'sample_count': row['total_bets'],
            }
        return {'roi': 0, 'hit_rate': 0, 'avg_hits': 0, 'sample_count': 0}

    def save_params(self, date, params, performance=None):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO algo_params (date, params, performance)
                     VALUES (?, ?, ?)''',
                  (date, json.dumps(params, ensure_ascii=False),
                   json.dumps(performance or {}, ensure_ascii=False)))
        conn.commit()
        conn.close()

    # --- 发现策略 ---

    def save_discovered_strategy(self, strategy_key, strategy_name, base_strategy, bias='custom',
                                  kelly_mult=1.0, tweak_params=None, source='discovered'):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO algo_discovered_strategies
                     (strategy_key, strategy_name, base_strategy, bias, kelly_mult, tweak_params, source,
                      roi_7d, hit_rate_7d, sample_count, status, discovered_at, retired_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'active', ?, NULL)''',
                  (strategy_key, strategy_name, base_strategy, bias, kelly_mult,
                   json.dumps(tweak_params or {}, ensure_ascii=False), source,
                   _now_cst().isoformat()))
        conn.commit()
        conn.close()

    def get_active_discovered_strategies(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM algo_discovered_strategies WHERE status = 'active'")
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def retire_strategy(self, strategy_key):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("UPDATE algo_discovered_strategies SET status = 'retired', retired_at = ? WHERE strategy_key = ?",
                  (_now_cst().isoformat(), strategy_key))
        conn.commit()
        conn.close()

    # --- 退火历史 ---

    def save_anneal_history(self, date, temperature, old_weights, new_weights, old_score, new_score, accepted):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO algo_anneal_history
                     (date, game, temperature, old_weights, new_weights, old_score, new_score, accepted)
                     VALUES (?, 'all', ?, ?, ?, ?, ?, ?)''',
                  (date, temperature,
                   json.dumps(old_weights, ensure_ascii=False), json.dumps(new_weights, ensure_ascii=False),
                   old_score, new_score, 1 if accepted else 0))
        conn.commit()
        conn.close()

    def get_anneal_count(self, days=7):
        """近N天退火次数"""
        conn = self._get_conn()
        c = conn.cursor()
        start_date = (_now_cst() - timedelta(days=days)).strftime('%Y-%m-%d')
        c.execute('SELECT COUNT(*) FROM algo_anneal_history WHERE date >= ?', (start_date,))
        count = c.fetchone()[0]
        conn.close()
        return count

    # --- 数据清理 ---

    def cleanup(self, bet_days=90, roi_days=180):
        conn = self._get_conn()
        c = conn.cursor()
        cutoff_bets = (_now_cst() - timedelta(days=bet_days)).strftime('%Y-%m-%d')
        cutoff_roi = (_now_cst() - timedelta(days=roi_days)).strftime('%Y-%m-%d')
        c.execute('DELETE FROM algo_settlements WHERE bet_id IN (SELECT id FROM algo_bets WHERE date < ?)', (cutoff_bets,))
        c.execute('DELETE FROM algo_bets WHERE date < ?', (cutoff_bets,))
        c.execute('DELETE FROM algo_roi_daily WHERE date < ?', (cutoff_roi,))
        c.execute('DELETE FROM algo_strategy_state WHERE date < ?', (cutoff_roi,))
        c.execute('DELETE FROM algo_gepa_state WHERE date < ?', (cutoff_roi,))
        c.execute('DELETE FROM algo_anneal_history WHERE date < ?', (cutoff_roi,))
        conn.commit()
        conn.close()

    # --- 同步weight-config.json ---

    def sync_to_weight_config(self, config):
        """将配置同步到weight-config.json（保持WeightedAnalyzer兼容）"""
        try:
            with open(WEIGHT_CONFIG_FILE, 'w') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AlgoDB] 同步weight-config.json失败: {e}")

    def load_weight_config(self):
        """从algo_gepa_state读取最新配置（主），如果为空则读weight-config.json"""
        state = self.get_latest_gepa_state()
        if state:
            config = dict(DEFAULT_WEIGHT_CONFIG)
            config.update(state['weights'])
            config['version'] = state.get('version', 1)
            config['algo_version'] = state.get('algo_version', 'v3.0')
            config['evolution_log'] = state.get('evolution_log', [])
            config['lock_config'] = state.get('lock_config', {})
            return config

        # fallback: 从JSON读
        try:
            with open(WEIGHT_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return dict(DEFAULT_WEIGHT_CONFIG)


# ===== GEPA P0权重进化器 =====

class GEPAEvolver:
    """P0权重进化器 — 从lottery_analyzer.py adjust_weights_from_backtest()迁出"""

    BOUNDS = {
        'freq': (0.10, 0.45), 'miss': (0.10, 0.45),
        'trend': (0.10, 0.40), 'zone': (0.05, 0.30),
        'cold_miss_front': (0.20, 0.60), 'cold_cycle_front': (0.15, 0.50),
        'cold_freq_front': (0.05, 0.45), 'cold_miss_back': (0.15, 0.50),
        'cold_cycle_back': (0.20, 0.60), 'cold_freq_back': (0.05, 0.45),
        'neighbor_bonus': (0.01, 0.08), 'gamma': (0.75, 0.95),
    }

    DEFAULT_LOCK_CONFIG = {
        'p0_weights': False,
        'cold_weights': False,
        'neighbor_bonus': False,
        'gamma': False,
    }

    def __init__(self, db):
        self.db = db

    def evolve(self, backtest_data, predictions_data,
               judge_prize_fn, get_hit_numbers_fn,
               strategy_map, default_config):
        """
        GEPA进化主函数
        所有外部依赖通过参数传入，不import lottery_analyzer.py的内部函数
        返回: evolved_config dict 或 None(无变化)
        """
        today_str = _now_cst().strftime('%Y-%m-%d')
        config = self.db.load_weight_config()
        lock_config = config.get('lock_config', self.DEFAULT_LOCK_CONFIG)

        # 全部锁定则跳过
        if all(lock_config.values()):
            print("[GEPA] 所有模块已锁定，跳过进化")
            return None

        recent = [bt for bt in backtest_data[-15:]
                  if bt.get('backtest_method') == 'current_version']
        if len(recent) < 1:
            return None

        # 收集AI推荐命中
        ai_hits_list, ai_prize_list, ai_by_game = self._collect_ai_hits(
            recent, predictions_data, judge_prize_fn, get_hit_numbers_fn)

        # 收集规则推荐命中
        mapped_stats, total_strategy_games = self._collect_rule_hits(recent, strategy_map)

        # 收集算法模块ROI
        algo_roi_signal = self._collect_algo_roi_signal()

        # 样本检查
        ai_sample = len(ai_hits_list)
        MIN_AI_SAMPLE = 3
        if ai_sample < MIN_AI_SAMPLE and total_strategy_games < 6:
            print(f"[GEPA] 样本不足(AI={ai_sample}, 规则={total_strategy_games})，暂不进化")
            return None

        # 计算核心指标
        ai_avg = sum(ai_hits_list) / max(len(ai_hits_list), 1) if ai_hits_list else 0
        ai_total_prize = sum(ai_prize_list)

        core_hits_list = mapped_stats.get('核心注', {}).get('hits', [0])
        cold_hits_list = mapped_stats.get('冷号注', {}).get('hits', [0])
        core_avg = sum(core_hits_list) / max(len(core_hits_list), 1)
        cold_avg = sum(cold_hits_list) / max(len(cold_hits_list), 1)

        print(f"[GEPA] AI均值命中={ai_avg:.2f}(n={ai_sample}), 核心={core_avg:.2f}, 冷号={cold_avg:.2f}, ROI信号={algo_roi_signal:+.2f}")

        # 步长决策
        if ai_avg < 1.0:
            step = 0.03
        elif ai_avg < 2.0:
            step = 0.02
        else:
            step = 0.01

        changes = []
        old_config = {k: config.get(k, default_config.get(k, 0)) for k in ALL_PARAM_KEYS}

        # ===== 策略调整逻辑 =====
        if ai_avg < 1.5 and ai_sample >= MIN_AI_SAMPLE:
            # AI命中差
            if algo_roi_signal < -0.3:
                # ROI信号: 回补优于追热
                if not lock_config.get('p0_weights', False):
                    config['miss'] = min(0.45, config.get('miss', 0.25) + step * 1.5)
                    config['freq'] = max(0.10, config.get('freq', 0.30) - step)
                if not lock_config.get('cold_weights', False):
                    config['cold_miss_front'] = min(0.60, config.get('cold_miss_front', 0.40) + step)
                    config['cold_miss_back'] = min(0.50, config.get('cold_miss_back', 0.30) + step * 0.5)
                changes.append(f"AI命中差({ai_avg:.1f})+ROI:回补优({algo_roi_signal:+.2f}) → miss+{step*1.5}")
            elif core_avg < cold_avg or algo_roi_signal < 0:
                if not lock_config.get('cold_weights', False):
                    config['cold_miss_front'] = min(0.60, config.get('cold_miss_front', 0.40) + step)
                    config['cold_miss_back'] = min(0.50, config.get('cold_miss_back', 0.30) + step * 0.5)
                changes.append(f"AI命中差({ai_avg:.1f})+冷号信号更强 → cold_miss +{step}")
            else:
                if not lock_config.get('p0_weights', False):
                    config['trend'] = min(0.40, config.get('trend', 0.25) + step)
                    config['zone'] = max(0.10, config.get('zone', 0.20) - step * 0.5)
                changes.append(f"AI命中差({ai_avg:.1f})+核心信号对 → trend+{step}, zone-{step*0.5}")

            if not lock_config.get('neighbor_bonus', False):
                if config.get('neighbor_bonus', 0.03) < 0.06:
                    config['neighbor_bonus'] = min(0.06, config.get('neighbor_bonus', 0.03) + 0.005)
                    changes.append(f"AI命中差 → neighbor_bonus +0.005 → {config['neighbor_bonus']:.3f}")

        elif ai_avg >= 2.0 and ai_sample >= MIN_AI_SAMPLE:
            # AI命中好
            if algo_roi_signal > 0.3:
                if not lock_config.get('p0_weights', False):
                    config['freq'] = min(0.45, config.get('freq', 0.30) + step * 0.5)
                    config['miss'] = max(0.10, config.get('miss', 0.25) - step * 0.5)
                changes.append(f"AI命中好+ROI:追热盈利({algo_roi_signal:+.2f}) → freq+{step*0.5}")
            elif core_avg > cold_avg + 0.3 or algo_roi_signal > 0:
                if not lock_config.get('p0_weights', False):
                    config['freq'] = min(0.45, config.get('freq', 0.30) + step * 0.5)
                    config['miss'] = max(0.10, config.get('miss', 0.25) - step * 0.5)
                changes.append(f"AI命中好+核心注驱动 → freq+{step*0.5}")
            elif cold_avg > core_avg + 0.3:
                if not lock_config.get('cold_weights', False):
                    config['cold_cycle_front'] = min(0.50, config.get('cold_cycle_front', 0.30) + step * 0.5)
                    config['cold_cycle_back'] = min(0.60, config.get('cold_cycle_back', 0.40) + step * 0.5)
                changes.append(f"AI命中好+冷号驱动 → cold_cycle+{step*0.5}")

            if not lock_config.get('neighbor_bonus', False):
                if config.get('neighbor_bonus', 0.03) > 0.01:
                    config['neighbor_bonus'] = max(0.01, config.get('neighbor_bonus', 0.03) - 0.005)
                    changes.append(f"AI命中好 → neighbor_bonus -0.005 → {config['neighbor_bonus']:.3f}")

        # 按彩种细化gamma
        for game, game_name in [('ssq', '双色球'), ('dlt', '大乐透'), ('qxc', '七星彩')]:
            game_hits = ai_by_game.get(game, [])
            if len(game_hits) >= 2:
                game_avg = sum(game_hits) / len(game_hits)
                game_baseline = {'ssq': 2.2, 'dlt': 1.8, 'qxc': 0.7}.get(game, 1.5)
                if not lock_config.get('gamma', False):
                    if game_avg < game_baseline * 0.5 and config.get('gamma', 0.88) > 0.80:
                        config['gamma'] = max(0.80, config.get('gamma', 0.88) - 0.01)
                        changes.append(f"{game_name}AI命中差({game_avg:.1f}) → gamma -0.01 → {config['gamma']:.2f}")
                    elif game_avg > game_baseline * 1.5 and config.get('gamma', 0.88) < 0.95:
                        config['gamma'] = min(0.95, config.get('gamma', 0.88) + 0.01)
                        changes.append(f"{game_name}AI命中好({game_avg:.1f}) → gamma +0.01 → {config['gamma']:.2f}")

        # 归一化
        self._normalize_cold_weights(config, lock_config)
        self._normalize_core_weights(config, lock_config)

        # 边界检查
        for key in ALL_PARAM_KEYS:
            if key in self.BOUNDS:
                lo, hi = self.BOUNDS[key]
                config[key] = max(lo, min(hi, config.get(key, default_config.get(key, 0))))

        if not changes:
            return None

        # 版本更新
        config['version'] = config.get('version', 1) + 1
        is_major = False
        total_samples = max(ai_sample, total_strategy_games)
        MIN_GAMES_FOR_MAJOR = 20
        for key in ALL_PARAM_KEYS:
            old_val = old_config.get(key, 0)
            new_val = config.get(key, 0)
            if abs(new_val - old_val) >= 0.04:
                if total_samples >= MIN_GAMES_FOR_MAJOR:
                    is_major = True
                else:
                    config[key] = old_val + (0.03 if new_val > old_val else -0.03)
                    changes = [c for c in changes if key not in c]
                    changes.append(f"样本不足({total_strategy_games}<{MIN_GAMES_FOR_MAJOR})，{key}限制±0.03")
                break

        if is_major:
            import re
            algo_version = config.get('algo_version', 'v3.0')
            m = re.match(r'(v\d+)\.(\d+)', algo_version)
            config['algo_version'] = f"{m.group(1)}.{int(m.group(2)) + 1}" if m else 'v3.0'

        # 进化日志
        evo_entry = {
            'date': today_str, 'trigger': 'AI推荐命中驱动',
            'ai_sample_size': ai_sample, 'ai_avg_hit': round(ai_avg, 2),
            'ai_total_prize': ai_total_prize, 'rule_sample_size': total_strategy_games,
            'changes': changes,
            'old_weights': {k: round(old_config.get(k, 0), 4) for k in ALL_PARAM_KEYS},
            'new_weights': {k: round(config.get(k, 0), 4) for k in ALL_PARAM_KEYS},
            'is_major': is_major, 'algo_version': config.get('algo_version', 'v3.0'),
        }
        evo_log = config.get('evolution_log', [])
        evo_log.append(evo_entry)
        config['evolution_log'] = evo_log[-30:]

        # 保存
        self.db.save_gepa_state(today_str, config, ai_avg_hit=ai_avg, step_size=step, is_major=is_major)

        major_tag = '🔴 重大更新' if is_major else '🟢 微调'
        print(f"[GEPA进化] {major_tag} → {config.get('algo_version', 'v3.0')} (AI均值={ai_avg:.2f})")
        for c in changes:
            print(f"  {c}")

        return config

    def _collect_ai_hits(self, recent, predictions, judge_prize_fn, get_hit_numbers_fn):
        ai_hits_list, ai_prize_list, ai_by_game = [], [], defaultdict(list)
        for bt in recent:
            bt_date = bt.get('date', '')
            day_pred = None
            for p in predictions:
                if p.get('date') == bt_date:
                    day_pred = p
                    break
            if not day_pred:
                continue
            for game in ['ssq', 'dlt', 'qxc']:
                if game not in bt:
                    continue
                actual_data = bt[game]
                ai_recs = day_pred.get(f'{game}_recs', [])
                if not ai_recs:
                    continue
                judge_fn = judge_prize_fn(game) if callable(judge_prize_fn) else None
                for rec in ai_recs:
                    try:
                        if game == 'ssq' and 'reds' in rec and 'actual_reds' in actual_data and judge_fn and get_hit_numbers_fn:
                            red_hits = len(get_hit_numbers_fn(rec.get('reds', []), actual_data.get('actual_reds', [])))
                            blue_hit = 1 if rec.get('blue') == actual_data.get('actual_blue') else 0
                            total = red_hits + blue_hit
                            prize = judge_fn(red_hits, blue_hit)
                        elif game == 'dlt' and 'front' in rec and 'actual_front' in actual_data and judge_fn and get_hit_numbers_fn:
                            front_hits = len(get_hit_numbers_fn(rec.get('front', []), actual_data.get('actual_front', [])))
                            back_hits = len(get_hit_numbers_fn(rec.get('back', []), actual_data.get('actual_back', [])))
                            total = front_hits + back_hits
                            prize = judge_fn(front_hits, back_hits)
                        elif game == 'qxc' and 'digits' in rec and 'actual_digits' in actual_data and judge_fn:
                            digit_hits = sum(1 for i in range(7) if rec.get('digits', [0]*7)[i] == actual_data.get('actual_digits', [0]*7)[i])
                            total = digit_hits
                            prize = judge_fn(digit_hits)
                        else:
                            continue
                        ai_hits_list.append(total)
                        ai_prize_list.append(prize.get('prize', 0) if isinstance(prize, dict) else 0)
                        ai_by_game[game].append(total)
                    except Exception:
                        continue
        return ai_hits_list, ai_prize_list, ai_by_game

    def _collect_rule_hits(self, recent, strategy_map):
        rule_strategy_stats = defaultdict(lambda: {'hits': [], 'games': 0})
        total_strategy_games = 0
        for bt in recent:
            for game in ['ssq', 'dlt', 'qxc']:
                if game not in bt:
                    continue
                for h in bt[game].get('hits', []):
                    s = h.get('strategy', '')
                    total = h.get('total', 0)
                    mapped_name = strategy_map.get(s, s) if strategy_map else s
                    rule_strategy_stats[mapped_name]['hits'].append(total)
                    rule_strategy_stats[mapped_name]['games'] += 1
                    total_strategy_games += 1
        return dict(rule_strategy_stats), total_strategy_games

    def _collect_algo_roi_signal(self):
        """从AlgoDB收集ROI信号"""
        try:
            p0_roi = 0
            p2_roi = 0
            for game in ['ssq', 'dlt', 'qxc']:
                p0_stats = self.db.get_strategy_roi('P0_CORE', game, days=7)
                p2_stats = self.db.get_strategy_roi('P2_RECOVERY', game, days=7)
                if p0_stats['sample_count'] > 0:
                    p0_roi += p0_stats['roi']
                if p2_stats['sample_count'] > 0:
                    p2_roi += p2_stats['roi']
            return p0_roi - p2_roi
        except Exception:
            return 0

    def _normalize_cold_weights(self, config, lock_config):
        if lock_config.get('cold_weights', False):
            return
        for suffix in ['front', 'back']:
            cm = config.get(f'cold_miss_{suffix}', 0.40 if suffix == 'front' else 0.30)
            cc = config.get(f'cold_cycle_{suffix}', 0.30 if suffix == 'front' else 0.40)
            cf = config.get(f'cold_freq_{suffix}', 0.30)
            cold_total = cm + cc + cf
            if cold_total > 0:
                config[f'cold_miss_{suffix}'] = round(cm / cold_total, 4)
                config[f'cold_cycle_{suffix}'] = round(cc / cold_total, 4)
                config[f'cold_freq_{suffix}'] = max(0.05, round(1.0 - config[f'cold_miss_{suffix}'] - config[f'cold_cycle_{suffix}'], 4))
                t2 = config[f'cold_miss_{suffix}'] + config[f'cold_cycle_{suffix}'] + config[f'cold_freq_{suffix}']
                if t2 > 0:
                    config[f'cold_miss_{suffix}'] = round(config[f'cold_miss_{suffix}'] / t2, 4)
                    config[f'cold_cycle_{suffix}'] = round(config[f'cold_cycle_{suffix}'] / t2, 4)
                    config[f'cold_freq_{suffix}'] = max(0, round(1.0 - config[f'cold_miss_{suffix}'] - config[f'cold_cycle_{suffix}'], 4))

    def _normalize_core_weights(self, config, lock_config):
        if lock_config.get('p0_weights', False):
            return
        f, m, t, z = config.get('freq', 0.30), config.get('miss', 0.25), config.get('trend', 0.25), config.get('zone', 0.20)
        total = f + m + t + z
        if total > 0:
            config['freq'] = round(f / total, 4)
            config['miss'] = round(m / total, 4)
            config['trend'] = round(t / total, 4)
            config['zone'] = max(0.05, round(1.0 - config['freq'] - config['miss'] - config['trend'], 4))
            t2 = config['freq'] + config['miss'] + config['trend'] + config['zone']
            if t2 > 0:
                config['freq'] = round(config['freq'] / t2, 4)
                config['miss'] = round(config['miss'] / t2, 4)
                config['trend'] = round(config['trend'] / t2, 4)
                config['zone'] = max(0, round(1.0 - config['freq'] - config['miss'] - config['trend'], 4))


# ===== 策略权重自适应 =====

class StrategySelector:
    INITIAL_WEIGHTS = {'P0_CORE': 0.40, 'P1_AGGRESSIVE': 0.20, 'P2_RECOVERY': 0.20, 'P3_BALANCED': 0.20}
    P0_MIN_WEIGHT = 0.30
    TEMPERATURE = 2.0
    MIN_SAMPLE = 7

    def update_weights(self, db, game, date):
        scores = {}
        total_samples = 0
        # 包含自定义策略
        all_keys = list(self.INITIAL_WEIGHTS.keys())
        for ds in db.get_active_discovered_strategies():
            all_keys.append(ds['strategy_key'])
            self.INITIAL_WEIGHTS.setdefault(ds['strategy_key'], 0.05)

        for key in all_keys:
            stats = db.get_strategy_roi(key, game, days=7)
            total_samples += stats['sample_count']
            scores[key] = stats['roi'] * 0.6 + stats['hit_rate'] * 0.4 if stats['sample_count'] >= self.MIN_SAMPLE else self.INITIAL_WEIGHTS.get(key, 0.05)

        weights = dict(self.INITIAL_WEIGHTS) if total_samples < self.MIN_SAMPLE else self._softmax(scores)
        if weights.get('P0_CORE', 0) < self.P0_MIN_WEIGHT:
            weights['P0_CORE'] = self.P0_MIN_WEIGHT
            total = sum(weights.values())
            weights = {k: v / total for k, v in weights.items()}

        for key, weight in weights.items():
            stats = db.get_strategy_roi(key, game, days=7)
            db.save_strategy_state(date, key, game, weight, roi_7d=stats['roi'], hit_rate_7d=stats['hit_rate'], sample_count=stats['sample_count'])
        return weights

    def get_current_weights(self, db, game):
        states = db.get_latest_strategy_states(game)
        weights = {}
        all_keys = list(self.INITIAL_WEIGHTS.keys())
        for ds in db.get_active_discovered_strategies():
            all_keys.append(ds['strategy_key'])
            self.INITIAL_WEIGHTS.setdefault(ds['strategy_key'], 0.05)
        for key in all_keys:
            weights[key] = states[key].get('weight', self.INITIAL_WEIGHTS.get(key, 0.05)) if key in states else self.INITIAL_WEIGHTS.get(key, 0.05)
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()} if total > 0 else dict(self.INITIAL_WEIGHTS)

    def _softmax(self, scores):
        exps = {k: math.exp(v / self.TEMPERATURE) for k, v in scores.items()}
        total = sum(exps.values())
        return {k: v / total for k, v in exps.items()}


# ===== 策略发现器 =====

class StrategyDiscoverer:
    MIN_SAMPLE = 14
    ROI_THRESHOLD = 0.5
    HIT_RATE_THRESHOLD = 0.15
    MAX_CUSTOM_STRATEGIES = 5

    def __init__(self, db):
        self.db = db

    def scan(self, game, date):
        """扫描是否有新策略变体值得创建"""
        # 检查已有自定义策略数量
        active = self.db.get_active_discovered_strategies()
        if len(active) >= self.MAX_CUSTOM_STRATEGIES:
            return []

        # 每周扫描一次（周一）
        if _now_cst().weekday() != 0:
            return []

        new_strategies = []
        for base_key in ['P0_CORE', 'P2_RECOVERY']:
            stats = self.db.get_strategy_roi(base_key, game, days=14)
            if stats['sample_count'] >= self.MIN_SAMPLE and stats['roi'] > self.ROI_THRESHOLD and stats['hit_rate'] > self.HIT_RATE_THRESHOLD:
                variant = self._create_variant(base_key, game, stats)
                if variant:
                    new_strategies.append(variant)
                    self.db.save_discovered_strategy(
                        strategy_key=variant['key'], strategy_name=variant['name'],
                        base_strategy=base_key, bias=variant['bias'],
                        kelly_mult=variant['kelly_mult'], source='discovered')
                    StrategyProfile.add_custom(variant)
                    print(f"[Discoverer] 发现新策略: {variant['name']} (基于{base_key}, ROI={stats['roi']:.2f})")

        # 淘汰表现差的自定义策略
        for ds in active:
            stats = self.db.get_strategy_roi(ds['strategy_key'], game, days=7)
            if stats['sample_count'] >= 7 and stats['roi'] <= 0:
                self.db.retire_strategy(ds['strategy_key'])
                print(f"[Discoverer] 淘汰策略: {ds['strategy_name']} (ROI={stats['roi']:.2f})")

        return new_strategies

    def _create_variant(self, base_key, game, stats):
        base = StrategyProfile.get(base_key)
        if not base:
            return None
        idx = len(self.db.get_active_discovered_strategies()) + 4  # P4, P5, ...
        if base_key == 'P0_CORE':
            return {'key': f'P{idx}_CORE_PLUS', 'name': f'P{idx}核心增强', 'bias': 'hot',
                    'kelly_mult': 1.2, 'source': 'discovered'}
        elif base_key == 'P2_RECOVERY':
            return {'key': f'P{idx}_DEEP_COLD', 'name': f'P{idx}深度回补', 'bias': 'cold',
                    'kelly_mult': 0.7, 'source': 'discovered'}
        return None


# ===== 模拟退火参数搜索 =====

class SimulatedAnnealer:
    EXPLORATION_PROB = 0.1
    MAX_PERTURBATION = 0.08
    COOLING_RATE = 0.95

    def __init__(self, db):
        self.db = db
        self.temperature = 1.0

    def should_explore(self):
        return random.random() < self.EXPLORATION_PROB

    def perturb(self, config, bounds):
        """对P0权重做随机扰动"""
        perturbed = dict(config)
        # 随机选2-3个参数扰动
        keys = random.sample(list(bounds.keys()), min(3, len(bounds)))
        for key in keys:
            lo, hi = bounds[key]
            delta = random.uniform(-self.temperature * self.MAX_PERTURBATION,
                                    self.temperature * self.MAX_PERTURBATION)
            perturbed[key] = max(lo, min(hi, perturbed.get(key, 0) + delta))
        return perturbed

    def evaluate(self, config):
        """评估配置得分：近7天ROI加权"""
        total_score = 0
        for game in ['ssq', 'dlt', 'qxc']:
            history = self.db.get_roi_history(game, days=7)
            for h in history:
                total_score += h.get('roi', 0) * h.get('total_cost', 1)
        return total_score

    def accept(self, old_score, new_score):
        """Metropolis准则"""
        if new_score > old_score:
            return True
        delta = new_score - old_score
        if self.temperature > 0.01:
            prob = math.exp(delta / self.temperature)
            return random.random() < prob
        return False

    def cool_down(self):
        self.temperature = max(0.1, self.temperature * self.COOLING_RATE)

    def try_anneal(self, config, lock_config):
        """尝试模拟退火探索"""
        if not self.should_explore():
            return None

        # 只扰动未锁定的参数
        allowed_bounds = {}
        for key, (lo, hi) in GEPAEvolver.BOUNDS.items():
            if key.startswith('freq') or key.startswith('miss') or key.startswith('trend') or key.startswith('zone'):
                if not lock_config.get('p0_weights', False):
                    allowed_bounds[key] = (lo, hi)
            elif key.startswith('cold_'):
                if not lock_config.get('cold_weights', False):
                    allowed_bounds[key] = (lo, hi)
            elif key == 'neighbor_bonus':
                if not lock_config.get('neighbor_bonus', False):
                    allowed_bounds[key] = (lo, hi)
            elif key == 'gamma':
                if not lock_config.get('gamma', False):
                    allowed_bounds[key] = (lo, hi)

        if not allowed_bounds:
            return None

        old_score = self.evaluate(config)
        perturbed = self.perturb(config, allowed_bounds)
        new_score = self.evaluate(perturbed)

        accepted = self.accept(old_score, new_score)
        today = _now_cst().strftime('%Y-%m-%d')
        self.db.save_anneal_history(today, self.temperature, config, perturbed, old_score, new_score, accepted)

        if accepted:
            print(f"[Annealer] 接受扰动 (score: {old_score:.2f}→{new_score:.2f}, T={self.temperature:.2f})")
            self.cool_down()
            return perturbed
        else:
            self.cool_down()
            return None


# ===== 组合投注优化 =====

class CombinationOptimizer:
    def __init__(self, db):
        self.db = db

    def optimize(self, game, history, base_recs, kelly_map, strategy_weights, budget_remaining):
        if budget_remaining < 2:
            return [], 0, 0

        candidates = []
        p1_rec = self._gen_aggressive_rec(game, history, kelly_map)
        if p1_rec:
            p1_rec.update({'strategy': 'P1_AGGRESSIVE', 'strategy_name': 'P1激进注', 'ev': self._calc_bet_ev(game, kelly_map)})
            candidates.append(p1_rec)

        p2_rec = self._gen_recovery_rec(game, history)
        if p2_rec:
            p2_rec.update({'strategy': 'P2_RECOVERY', 'strategy_name': 'P2回补注', 'ev': self._calc_bet_ev(game, kelly_map) * 0.8})
            candidates.append(p2_rec)

        p3_rec = self._gen_balanced_rec(game, history, base_recs)
        if p3_rec:
            p3_rec.update({'strategy': 'P3_BALANCED', 'strategy_name': 'P3均衡注', 'ev': self._calc_bet_ev(game, kelly_map)})
            candidates.append(p3_rec)

        if not candidates:
            return [], 0, 0

        for c in candidates:
            c['priority'] = strategy_weights.get(c['strategy'], 0.20) * max(c['ev'], 0)
        candidates.sort(key=lambda x: x['priority'], reverse=True)

        selected, total_cost = [], 0
        for c in candidates:
            if total_cost + 2 <= budget_remaining:
                selected.append(c)
                total_cost += 2

        expected_roi = sum(c['ev'] for c in selected) / total_cost if total_cost > 0 else 0
        return selected, total_cost, expected_roi

    def _gen_aggressive_rec(self, game, history, kelly_map):
        try:
            from lottery_analyzer import WeightedAnalyzer
            kelly = kelly_map.get(game, 0)
            kelly_bias = math.tanh(kelly * 20) * 0.5 * 1.5
            wa = WeightedAnalyzer(history)
            if game == 'ssq':
                analysis = wa.analyze_ssq()
                recs = wa.generate_recs_ssq(analysis, kelly_bias=kelly_bias)
                if recs: return {'reds': recs[0].get('reds', []), 'blue': recs[0].get('blue', 1)}
            elif game == 'dlt':
                analysis = wa.analyze_dlt()
                recs = wa.generate_recs_dlt(analysis, kelly_bias=kelly_bias)
                if recs: return {'front': recs[0].get('front', []), 'back': recs[0].get('back', [])}
            elif game == 'qxc':
                analysis = wa.analyze_qxc()
                recs = wa.generate_recs_qxc(analysis, kelly_bias=kelly_bias)
                if recs: return {'digits': recs[0].get('digits', [0]*7)}
        except Exception as e:
            print(f"[Algo] P1生成失败: {e}")
        return None

    def _gen_recovery_rec(self, game, history):
        try:
            from lottery_analyzer import WeightedAnalyzer
            wa = WeightedAnalyzer(history, weight_freq=0.15, weight_miss=0.50, weight_trend=0.15, weight_zone=0.20)
            if game == 'ssq':
                analysis = wa.analyze_ssq()
                recs = wa.generate_recs_ssq(analysis, kelly_bias=-0.3)
                if recs: return {'reds': recs[0].get('reds', []), 'blue': recs[0].get('blue', 1)}
            elif game == 'dlt':
                analysis = wa.analyze_dlt()
                recs = wa.generate_recs_dlt(analysis, kelly_bias=-0.3)
                if recs: return {'front': recs[0].get('front', []), 'back': recs[0].get('back', [])}
            elif game == 'qxc':
                analysis = wa.analyze_qxc()
                recs = wa.generate_recs_qxc(analysis, kelly_bias=-0.3)
                if recs: return {'digits': recs[0].get('digits', [0]*7)}
        except Exception as e:
            print(f"[Algo] P2生成失败: {e}")
        return None

    def _gen_balanced_rec(self, game, history, base_recs):
        try:
            from lottery_analyzer import WeightedAnalyzer
            wa = WeightedAnalyzer(history)
            if game == 'ssq':
                covered_zones = set()
                for rec in base_recs:
                    for r in rec.get('reds', []):
                        covered_zones.add((r - 1) // 11)
                uncovered = {0, 1, 2} - covered_zones
                if not uncovered: return None
                analysis = wa.analyze_ssq()
                red_weights = dict(analysis.get('red_weights', []))
                for n in range(1, 34):
                    if (n - 1) // 11 in uncovered:
                        red_weights[n] = red_weights.get(n, 0) + 0.1
                top6 = sorted(red_weights.items(), key=lambda x: -x[1])[:6]
                reds = sorted([n for n, _ in top6])
                blue = analysis.get('blue_weights', [(1, 0)])[0][0]
                return {'reds': reds, 'blue': blue}
            elif game == 'dlt':
                covered_zones = set()
                for rec in base_recs:
                    for r in rec.get('front', []):
                        covered_zones.add((r - 1) // 7)
                uncovered = {0, 1, 2, 3, 4} - covered_zones
                if not uncovered: return None
                analysis = wa.analyze_dlt()
                front_weights = dict(analysis.get('front_weights', []))
                for n in range(1, 36):
                    if (n - 1) // 7 in uncovered:
                        front_weights[n] = front_weights.get(n, 0) + 0.1
                top5 = sorted(front_weights.items(), key=lambda x: -x[1])[:5]
                front = sorted([n for n, _ in top5])
                back_w = analysis.get('back_weights', [(1, 0)])
                back = [back_w[0][0]]
                if len(back_w) > 1: back.append(back_w[1][0])
                return {'front': front, 'back': sorted(back)}
            elif game == 'qxc':
                analysis = wa.analyze_qxc()
                digits = [analysis.get(f'pos{i}_top', [0])[0] if f'pos{i}_top' in analysis else 0 for i in range(7)]
                return {'digits': digits}
        except Exception as e:
            print(f"[Algo] P3生成失败: {e}")
        return None

    def _calc_bet_ev(self, game, kelly_map):
        try:
            from lottery_analyzer import PRIZE_TIERS
            tiers = PRIZE_TIERS.get(game, [])
            if not tiers: return -1.5
            total_ev = sum(t['prize'] * t['prob'] for t in tiers)
            kelly = kelly_map.get(game, 0)
            return total_ev * (1.0 + kelly * 5) - 2
        except Exception:
            return -1.5


# ===== ROI追踪+结算 =====

class ROITracker:
    def __init__(self, db):
        self.db = db

    def settle(self, yesterday=None):
        """结算昨日pending注"""
        if not yesterday:
            yesterday = (_now_cst() - timedelta(days=1)).strftime('%Y-%m-%d')

        try:
            from lottery_analyzer import (fetch_ssq_history, fetch_dlt_history, fetch_qxc_history,
                                           judge_prize_ssq, judge_prize_dlt, judge_prize_qxc, _get_hit_numbers)
        except ImportError:
            print("[Algo] 无法导入lottery_analyzer，跳过结算")
            return

        pending = self.db.get_pending_bets(date=yesterday)
        if not pending:
            print(f"[Algo] {yesterday} 无pending注")
            return

        actual_data = {}
        for game, fetch_fn in [('ssq', fetch_ssq_history), ('dlt', fetch_dlt_history), ('qxc', fetch_qxc_history)]:
            try:
                data = fetch_fn(1)
                if data: actual_data[game] = data[0]
            except Exception:
                pass

        settled_count = 0
        for bet in pending:
            game = bet['game']
            if game not in actual_data:
                continue
            numbers = json.loads(bet['numbers']) if isinstance(bet['numbers'], str) else bet['numbers']
            actual = actual_data[game]
            prize = self._judge_prize(game, numbers, actual, judge_prize_ssq, judge_prize_dlt, judge_prize_qxc, _get_hit_numbers)
            self.db.settle_bet(bet['id'], actual, prize['hit_count'], prize.get('tier', 0),
                               prize.get('name', '未中奖'), prize.get('prize', 0), bet.get('user_id', 'default'))
            settled_count += 1
        print(f"[Algo] 结算{settled_count}注")

    def _judge_prize(self, game, numbers, actual, judge_ssq, judge_dlt, judge_qxc, get_hit_numbers):
        try:
            if game == 'ssq':
                reds = numbers.get('reds', [])
                blue = numbers.get('blue', 0)
                actual_reds = actual.get('reds', actual.get('red', []))
                actual_blue = actual.get('blue', 0)
                red_hits = len(get_hit_numbers(reds, actual_reds))
                blue_hit = 1 if blue == actual_blue else 0
                prize = judge_ssq(red_hits, blue_hit)
                prize['hit_count'] = red_hits + blue_hit
                return prize
            elif game == 'dlt':
                front = numbers.get('front', [])
                back = numbers.get('back', [])
                actual_front = actual.get('front', actual.get('front_area', []))
                actual_back = actual.get('back', actual.get('back_area', []))
                front_hits = len(get_hit_numbers(front, actual_front))
                back_hits = len(get_hit_numbers(back, actual_back))
                prize = judge_dlt(front_hits, back_hits)
                prize['hit_count'] = front_hits + back_hits
                return prize
            elif game == 'qxc':
                digits = numbers.get('digits', [0]*7)
                actual_digits = actual.get('digits', actual.get('qxc', [0]*7))
                if isinstance(actual_digits, str): actual_digits = [int(d) for d in actual_digits]
                digit_hits = sum(1 for i in range(7) if i < len(digits) and i < len(actual_digits) and digits[i] == actual_digits[i])
                prize = judge_qxc(digit_hits)
                prize['hit_count'] = digit_hits
                return prize
        except Exception as e:
            print(f"[Algo] 奖级判定失败: {e}")
        return {'tier': 0, 'name': '未中奖', 'prize': 0, 'hit_count': 0}

    def calc_daily_roi(self, date):
        """计算每日ROI"""
        for game in ['ssq', 'dlt', 'qxc']:
            settled = self.db.get_settled_bets(date=date, game=game)
            if not settled: continue
            total_cost = sum(s['cost'] for s in settled)
            total_prize = sum(s['prize_amount'] for s in settled)
            roi = total_prize / total_cost if total_cost > 0 else 0
            hit_rate = sum(1 for s in settled if s['prize_tier'] > 0) / len(settled)
            avg_hit = sum(s['hit_count'] for s in settled) / len(settled)
            strategy_breakdown = {}
            for s in settled:
                st = s['strategy']
                if st not in strategy_breakdown: strategy_breakdown[st] = {'cost': 0, 'prize': 0, 'count': 0}
                strategy_breakdown[st]['cost'] += s['cost']
                strategy_breakdown[st]['prize'] += s['prize_amount']
                strategy_breakdown[st]['count'] += 1
            self.db.save_roi_daily(date, 'default', game, total_cost, total_prize, roi, hit_rate, avg_hit, len(settled), strategy_breakdown)

        all_settled = self.db.get_settled_bets(date=date)
        if all_settled:
            total_cost = sum(s['cost'] for s in all_settled)
            total_prize = sum(s['prize_amount'] for s in all_settled)
            roi = total_prize / total_cost if total_cost > 0 else 0
            hit_rate = sum(1 for s in all_settled if s['prize_tier'] > 0) / len(all_settled)
            avg_hit = sum(s['hit_count'] for s in all_settled) / len(all_settled)
            self.db.save_roi_daily(date, 'default', 'all', total_cost, total_prize, roi, hit_rate, avg_hit, len(all_settled))

    def record_bets(self, date, game, recs, kelly_map):
        for rec in recs:
            strategy = rec.get('strategy', 'P0核心注')
            numbers = {}
            if game == 'ssq': numbers = {'reds': rec.get('reds', []), 'blue': rec.get('blue', 1)}
            elif game == 'dlt': numbers = {'front': rec.get('front', []), 'back': rec.get('back', [])}
            elif game == 'qxc': numbers = {'digits': rec.get('digits', [0]*7)}
            self.db.save_bet('default', date, game, strategy, numbers, 2, kelly_map.get(game, 0), rec.get('ev', 0))

    def get_roi_summary(self, days=7):
        summary = {}
        for game in ['ssq', 'dlt', 'qxc', 'all']:
            history = self.db.get_roi_history(game, days=days)
            if history:
                avg_roi = sum(h['roi'] for h in history) / len(history)
                avg_hit = sum(h['avg_hit_count'] for h in history) / len(history)
                summary[game] = {'days': len(history), 'avg_roi': round(avg_roi, 4), 'avg_hit': round(avg_hit, 2),
                                 'total_cost': sum(h['total_cost'] for h in history),
                                 'total_prize': sum(h['total_prize'] for h in history), 'history': history}
        return summary


# ===== 统一算法引擎 =====

class AlgoEngine:
    """统一算法引擎 — 唯一入口"""

    def __init__(self):
        self.db = AlgoDB()
        self.gepa = GEPAEvolver(self.db)
        self.selector = StrategySelector()
        self.optimizer = CombinationOptimizer(self.db)
        self.roi_tracker = ROITracker(self.db)
        self.discoverer = StrategyDiscoverer(self.db)
        self.annealer = SimulatedAnnealer(self.db)

    def evolve(self, backtest_data=None, predictions_data=None,
               judge_prize_fn=None, get_hit_numbers_fn=None,
               strategy_map=None, default_config=None):
        """统一进化入口"""
        today = _now_cst().strftime('%Y-%m-%d')

        # 1. GEPA P0权重进化
        evolved_config = None
        if backtest_data is not None and predictions_data is not None:
            evolved_config = self.gepa.evolve(
                backtest_data, predictions_data,
                judge_prize_fn, get_hit_numbers_fn,
                strategy_map, default_config or DEFAULT_WEIGHT_CONFIG)

        config = evolved_config or self.db.load_weight_config()
        lock_config = config.get('lock_config', GEPAEvolver.DEFAULT_LOCK_CONFIG)

        # 2. 策略权重自适应
        for game in ['ssq', 'dlt', 'qxc']:
            self.selector.update_weights(self.db, game, today)

        # 3. 策略发现扫描
        for game in ['ssq', 'dlt', 'qxc']:
            self.discoverer.scan(game, today)

        # 4. 模拟退火探索
        if not all(lock_config.values()):
            annealed = self.annealer.try_anneal(config, lock_config)
            if annealed:
                config.update({k: annealed[k] for k in ALL_PARAM_KEYS if k in annealed})
                self.db.save_gepa_state(today, config)

        # 5. 同步weight-config.json
        self.db.sync_to_weight_config(config)

        # 6. 保存参数快照
        params = {}
        for game in ['ssq', 'dlt', 'qxc']:
            params[f'{game}_strategy_weights'] = self.selector.get_current_weights(self.db, game)
        params['p0_weights'] = {k: config.get(k, 0) for k in ALL_PARAM_KEYS}
        self.db.save_params(today, params)

        print(f"[AlgoEngine] 进化完成 → {config.get('algo_version', 'v3.0')}")
        return config

    def optimize(self, ssq_result, dlt_result, qxc_result, kelly_map, budget=10):
        """组合优化"""
        today = _now_cst().strftime('%Y-%m-%d')
        base_cost = 4 * 2
        algo_recs, algo_costs = {}, {}

        for game, result in [('ssq', ssq_result), ('dlt', dlt_result), ('qxc', qxc_result)]:
            if not result: continue
            history, recs = result[0], result[1] if isinstance(result, tuple) else ([], [])
            base_recs = recs if isinstance(recs, list) else []
            strategy_weights = self.selector.get_current_weights(self.db, game)
            new_recs, cost, expected_roi = self.optimizer.optimize(
                game, history, base_recs, kelly_map, strategy_weights, budget - base_cost)
            algo_recs[game] = new_recs
            algo_costs[game] = cost
            all_recs = list(base_recs) + new_recs
            self.roi_tracker.record_bets(today, game, all_recs, kelly_map)
            if new_recs:
                print(f"[Algo] {game} 追加{len(new_recs)}注 (成本{cost}元)")

        roi_summary = self.roi_tracker.get_roi_summary(days=7)
        return AlgoResult(algo_recs, algo_costs, kelly_map, roi_summary, self.selector, self.db)

    def settle(self, yesterday=None):
        """结算昨日"""
        if not yesterday:
            yesterday = (_now_cst() - timedelta(days=1)).strftime('%Y-%m-%d')
        self.roi_tracker.settle(yesterday)
        self.roi_tracker.calc_daily_roi(yesterday)

    def daily_update(self):
        """完整每日流程: settle → evolve → cleanup
        v3.0: 尝试使用Orchestrator，失败则降级到原有流程
        Orchestrator返回context(模式/贝叶斯修正/马尔可夫信号)，写入DB供lottery_analyzer读取
        """
        try:
            from algo_orchestrator import AlgoOrchestrator
            orch = AlgoOrchestrator()
            context = orch.daily_run()
            
            # 将Orchestrator context写入DB，供lottery_analyzer读取
            if context:
                self._save_orchestrator_context(context)
            
            self.db.cleanup()
            print("[AlgoEngine] v3.0 Orchestrator每日更新完成")
        except ImportError:
            # 降级到v2.0流程
            self.settle()
            self.db.cleanup()
            print("[AlgoEngine] v2.0 降级模式每日更新完成")
    
    def _save_orchestrator_context(self, context):
        """将Orchestrator输出的关键信号写入DB，供lottery_analyzer读取"""
        today = _now_cst().strftime('%Y-%m-%d')
        
        # 写入algo_orchestrator_context表（已存在）
        try:
            conn = self.db._get_conn()
            c = conn.cursor()
            
            # 确保表存在
            c.execute('''CREATE TABLE IF NOT EXISTS algo_orchestrator_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                context TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(date))''')
            
            c.execute('''INSERT OR REPLACE INTO algo_orchestrator_context (date, context, created_at)
                         VALUES (?, ?, ?)''',
                      (today, json.dumps(context, ensure_ascii=False, default=str), _now_cst().isoformat()))
            
            # 单独存储贝叶斯修正系数到便捷表（lottery_analyzer直接读）
            c.execute('''CREATE TABLE IF NOT EXISTS algo_bayesian_weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                game TEXT NOT NULL,
                adjustments TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(date, game))''')
            
            bayesian_adj = context.get('bayesian_adj', {})
            for game, adj in bayesian_adj.items():
                c.execute('''INSERT OR REPLACE INTO algo_bayesian_weights (date, game, adjustments, created_at)
                             VALUES (?, ?, ?, ?)''',
                          (today, game, json.dumps(adj, ensure_ascii=False), _now_cst().isoformat()))
            
            conn.commit()
            conn.close()
            
            mode = context.get('mode', 'normal')
            entropy = context.get('entropy_ratio', 1.0)
            adj_games = list(bayesian_adj.keys()) if bayesian_adj else []
            print(f"[AlgoEngine] context已写入DB: 模式={mode}, 熵比={entropy:.4f}, 贝叶斯修正={adj_games}")
        except Exception as e:
            print(f"[AlgoEngine] context写入DB失败: {e}")


# ===== 输出结果 =====

class AlgoResult:
    def __init__(self, algo_recs, algo_costs, kelly_map, roi_summary, selector, db):
        self.algo_recs = algo_recs
        self.algo_costs = algo_costs
        self.kelly_map = kelly_map
        self.roi_summary = roi_summary
        self.selector = selector
        self.db = db

    def format_section(self):
        lines = ['\n---\n', '## 🧮 统一算法引擎 — 进化+优化\n']

        # 近7天ROI
        if self.roi_summary:
            lines.append('### 📊 近7天ROI\n')
            lines.append('| 日期 | 双色球 | 大乐透 | 七星彩 | 综合 |')
            lines.append('|------|--------|--------|--------|------|')
            dates = set()
            for game in ['ssq', 'dlt', 'qxc']:
                if game in self.roi_summary:
                    for h in self.roi_summary[game].get('history', []):
                        dates.add(h['date'])
            if dates:
                for d in sorted(dates, reverse=True):
                    row = f"| {d[5:]} |"
                    for game in ['ssq', 'dlt', 'qxc']:
                        val = ''
                        if game in self.roi_summary:
                            for h in self.roi_summary[game].get('history', []):
                                if h['date'] == d: val = f"{h['roi']:.2f}"; break
                        row += f" {val} |"
                    val = ''
                    if 'all' in self.roi_summary:
                        for h in self.roi_summary['all'].get('history', []):
                            if h['date'] == d: val = f"{h['roi']:.2f}"; break
                    row += f" {val} |"
                    lines.append(row)
                row = "| **均值** |"
                for game in ['ssq', 'dlt', 'qxc']:
                    if game in self.roi_summary: row += f" **{self.roi_summary[game]['avg_roi']:.2f}** |"
                    else: row += " - |"
                if 'all' in self.roi_summary: row += f" **{self.roi_summary['all']['avg_roi']:.2f}** |"
                else: row += " - |"
                lines.append(row)
            lines.append('')

        # 策略权重
        lines.append('### ⚖️ 当前策略权重\n')
        lines.append('| 策略 | 双色球 | 大乐透 | 七星彩 |')
        lines.append('|------|--------|--------|--------|')
        for key, name in [('P0_CORE', 'P0核心注'), ('P1_AGGRESSIVE', 'P1激进注'),
                          ('P2_RECOVERY', 'P2回补注'), ('P3_BALANCED', 'P3均衡注')]:
            row = f"| {name} |"
            for game in ['ssq', 'dlt', 'qxc']:
                weights = self.selector.get_current_weights(self.db, game)
                row += f" {weights.get(key, 0):.0%} |"
            lines.append(row)
        lines.append('')

        # 算法注
        lines.append('### 🎯 算法注推荐 (预算内追加)\n')
        has_algo = False
        for game, game_name in [('ssq', '双色球'), ('dlt', '大乐透'), ('qxc', '七星彩')]:
            recs = self.algo_recs.get(game, [])
            cost = self.algo_costs.get(game, 0)
            if recs:
                has_algo = True
                lines.append(f"**{game_name}** (追加{cost}元):")
                for rec in recs:
                    sn = rec.get('strategy_name', '算法注')
                    if game == 'ssq':
                        lines.append(f"- [{sn}] `{' '.join(f'{r:02d}' for r in rec.get('reds', []))}` + 蓝`{rec.get('blue', 0):02d}`")
                    elif game == 'dlt':
                        lines.append(f"- [{sn}] `{' '.join(f'{r:02d}' for r in rec.get('front', []))}` + 后`{' '.join(f'{r:02d}' for r in rec.get('back', []))}`")
                    elif game == 'qxc':
                        lines.append(f"- [{sn}] `{''.join(str(d) for d in rec.get('digits', [0]*7))}`")
                lines.append('')
        if not has_algo:
            lines.append('本期无追加算法注\n')

        return '\n'.join(lines)


# ===== 便捷入口 =====

def run_algo_evolve(backtest_data, predictions_data, judge_prize_fn, get_hit_numbers_fn, strategy_map, default_config):
    """便捷入口：供lottery_analyzer.py调用"""
    try:
        engine = AlgoEngine()
        return engine.evolve(backtest_data, predictions_data, judge_prize_fn, get_hit_numbers_fn, strategy_map, default_config)
    except Exception as e:
        print(f"[AlgoEngine] 进化异常: {e}")
        return None


def run_algo_optimize(ssq_result, dlt_result, qxc_result, kelly_map, budget=10):
    """便捷入口：供lottery_analyzer.py调用"""
    try:
        engine = AlgoEngine()
        return engine.optimize(ssq_result, dlt_result, qxc_result, kelly_map, budget)
    except Exception as e:
        print(f"[AlgoEngine] 优化异常: {e}")
        return None


def run_algo_daily_update():
    """便捷入口：供scheduler.py调用"""
    try:
        engine = AlgoEngine()
        engine.daily_update()
    except Exception as e:
        print(f"[AlgoEngine] 每日更新异常: {e}")


if __name__ == '__main__':
    print("=" * 50)
    print("刘海蟾点金 - 统一算法引擎 v3.0 自检")
    print("=" * 50)
    db = AlgoDB()
    print(f"✓ 数据库: {db.db_path}")
    state = db.get_latest_gepa_state()
    if state:
        print(f"✓ GEPA状态: v{state.get('version', '?')}, {state.get('algo_version', '?')}")
        w = state.get('weights', {})
        print(f"  P0权重: freq={w.get('freq',0):.2f} miss={w.get('miss',0):.2f} trend={w.get('trend',0):.2f} zone={w.get('zone',0):.2f}")
    selector = StrategySelector()
    weights = selector.get_current_weights(db, 'ssq')
    print(f"✓ 策略权重: {weights}")
    print("\n自检通过 ✓")
