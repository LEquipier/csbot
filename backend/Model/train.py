# -*- coding: utf-8 -*-
"""
Adaptive Rule-based Backtester with Daily Top-K Selection (BUFF & YYYP)
- 只用过去 1/7/30 天触发（无未来泄露）
- 动态 TP/SL；卖出手续费 2%；双边滑点 0.3%/0.3%
- 在线学习反馈：策略/平台 ROI-EMA；新增“按饰品 item_ema”
- 强制平仓 100 天；容量/冲击（名义上限、吃单比例、冷却期）
- 测试期自动截断至“昨天”；支持 state 热启动
- 新增：每日对候选信号打分，只买 Top-K（最有潜力）
- 已针对 T+7 做六项强化：更挑剔的入场、T+7 后转弱/回撤退出、点差/跨平台一致性惩罚等
"""

import os
import glob
import json
import random
import warnings
import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# =========================
# 路径与基本配置
# =========================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "dataset/")  # 指向 dataset 根目录，支持全刀型

INITIAL_CASH = 100000.0
SELL_FEE_RATE = 0.02
MAX_HOLD_DAYS = 100
MIN_HOLD_DAYS = 7     # T+7：买入后至少 7 天才可卖出

TRAIN_START = "2023-01-01"
TRAIN_END   = "2024-12-31"
TEST_START  = "2025-01-01"

# —— 仓位与并发（T+7 情况下更保守）——
ORDER_FRACTION = 0.08        # 单笔用可用现金比例（原 0.08 -> 0.06）
MAX_POSITIONS  = 16          # 并发持仓上限（原 20 -> 12）
MAX_NEW_BUYS_PER_DAY = 2     # 每日最多新开仓（原 2 -> 1）

MIN_QTY        = 1
MIN_PRICE      = 1.0         # 有效卖价阈值

# 流动性过滤
MIN_SELL_NUM = 1
MIN_BUY_NUM  = 1

# 数据质量过滤（新增）
MIN_AVG_VOLUME = .0        # 历史平均交易量阈值（两平台）
MAX_DAILY_PRICE_CHANGE = 1.0 # 最大日涨跌幅（100%），超过此值标记为异常

# —— 容量与滑点 ——
NOTIONAL_CAP_PER_TRADE = 20000.0  # 名义上限/笔
ALPHA_QTY_CAP = 0.20              # 最多吃走卖单量的 20%
SLIP_BUY = 0.003                  # 买入滑点 0.3%
SLIP_SELL = 0.003                 # 卖出滑点 0.3%
COOLDOWN_DAYS_PER_GOOD = 14       # 冷却期（原 10 -> 14）

# —— 奖励 EMA 半衰期（更平滑）——
HALFLIFE_DAYS = 60
EMA_DECAY = np.exp(np.log(0.5) / HALFLIFE_DAYS)  # 越接近 1 表示衰减慢
ALPHA_EMA = 1 - EMA_DECAY

# —— 策略族（T+7 调参后）——
# (sid, dip1d, mom7, mom30, k_tp, k_sl, tp_min, sl_min)
STRATEGY_FAMILY = [
    ("S1", -0.010,  0.006, 0.012, 5.6, 2.2, 0.035, 0.035),
    ("S2", -0.015,  0.012, 0.018, 6.2, 2.6, 0.040, 0.035),
    ("S3", -0.006,  0.000, 0.012, 4.8, 2.0, 0.030, 0.030),
    ("S4", -0.020,  0.018, 0.022, 6.8, 3.0, 0.045, 0.040),
    ("S5",  0.000,  0.020, 0.030, 4.2, 1.6, 0.050, 0.028),
]
PLATFORMS = ["BUFF", "YYYP"]

# 多臂参数
EPSILON_START = 0.35
EPSILON_END   = 0.03
DECAY_STEPS   = 365
SOFTMAX_TEMP_START = 1.0
SOFTMAX_TEMP_END   = 0.2
TEMP_DECAY_STEPS   = 365

# 特征窗口
VOL_WINDOW = 14
MOM7_LAG   = 7
MOM30_LAG  = 30

# ============== Top-K 打分权重（可调）=============
W_R7 = 1.0
W_R30 = 1.0
W_DIP1D = 0.5
W_VOL = 1.0
W_STRAT = 0.6
W_PLAT = 0.6
W_ITEM = 0.8

# =========================
# 工具函数
# =========================
def resolve_cutoff_date() -> pd.Timestamp:
    today = datetime.now().date()
    return pd.to_datetime(today - timedelta(days=1))

# =========================
# 数据加载 + 清洗（0 → NaN）
# =========================
def load_all_items(data_dir: str) -> pd.DataFrame:
    """
    加载所有刀型的数据，遍历 dataset/*_db/items/*.csv 文件。
    """
    frames = []
    good_id_to_name = {}
    for db_dir in glob.glob(os.path.join(data_dir, "*_db")):
        items_dir = os.path.join(db_dir, "items")
        if not os.path.exists(items_dir):
            continue

        print(f"📂 加载刀型数据：{os.path.basename(db_dir)}")
        for fp in sorted(glob.glob(os.path.join(items_dir, "*.csv"))):
            try:
                df = pd.read_csv(fp, encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(fp, encoding="gbk")
            if "date" not in df.columns:
                continue

            df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
            df = df.dropna(subset=["date"]).copy()
            df["date"] = df["date"].dt.tz_convert(None)

            item_name = os.path.splitext(os.path.basename(fp))[0]
            if "good_id" not in df.columns:
                df["good_id"] = item_name
            else:
                df["good_id"] = df["good_id"].fillna(item_name)

            for good_id in df["good_id"].unique():
                good_id_to_name[str(good_id)] = item_name

            for plat in PLATFORMS:
                for col in [f"{plat}_sell_price", f"{plat}_buy_price",
                            f"{plat}_sell_num",  f"{plat}_buy_num"]:
                    if col not in df.columns:
                        df[col] = np.nan

            price_cols = [f"{p}_sell_price" for p in PLATFORMS] + \
                         [f"{p}_buy_price"  for p in PLATFORMS]
            for c in price_cols:
                df[c] = pd.to_numeric(df[c], errors="coerce")
                df.loc[df[c] == 0.0, c] = np.nan

            frames.append(df)

    if not frames:
        raise FileNotFoundError(f"未找到任何CSV文件：{data_dir}/*_db/items/*.csv")

    print(f"📊 共加载 {len(frames)} 个物品的数据文件")
    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.drop_duplicates(subset=["date", "good_id"])
    all_df = all_df.sort_values(["date", "good_id"]).reset_index(drop=True)
    all_df["item_name"] = all_df["good_id"].astype(str).map(good_id_to_name)
    return all_df

# =========================
# 数据质量过滤
# =========================
def filter_data_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    1) 排除平均成交量过低的物品；
    2) 标记价格异常变动（1d/2d > 100%）的日期（并在回测时排除）。
    """
    print("🔍 开始数据质量过滤...")
    filtered_frames = []
    total_items = df['good_id'].nunique()
    processed_items = 0
    excluded_items = 0

    for good_id, item_df in df.groupby('good_id'):
        processed_items += 1
        if processed_items % 100 == 0:
            print(f"  已处理 {processed_items}/{total_items} 个物品...")

        item_df = item_df.sort_values('date').copy()

        # 平台合计成交量
        volume_cols = []
        for plat in PLATFORMS:
            sell_col = f"{plat}_sell_num"
            buy_col  = f"{plat}_buy_num"
            if sell_col in item_df.columns and buy_col in item_df.columns:
                item_df[f"{plat}_total_volume"] = (
                    pd.to_numeric(item_df[sell_col], errors='coerce').fillna(0) +
                    pd.to_numeric(item_df[buy_col],  errors='coerce').fillna(0)
                )
                volume_cols.append(f"{plat}_total_volume")

        if volume_cols:
            avg_volume = item_df[volume_cols].mean().mean()
            if avg_volume < MIN_AVG_VOLUME:
                excluded_items += 1
                print(f"    ❌ 排除低流动性物品 {good_id}（平均交易量 {avg_volume:.1f} < {MIN_AVG_VOLUME}）")
                continue

        # 标记异常价格日期
        item_df['is_price_abnormal'] = False
        for plat in PLATFORMS:
            price_col = f"{plat}_sell_price"
            if price_col in item_df.columns:
                price_series = pd.to_numeric(item_df[price_col], errors='coerce')
                ret_1d = price_series.pct_change(1)
                ret_2d = price_series.pct_change(2)
                abnormal_1d = (ret_1d.abs() > MAX_DAILY_PRICE_CHANGE)
                abnormal_2d = (ret_2d.abs() > MAX_DAILY_PRICE_CHANGE)
                item_df.loc[abnormal_1d | abnormal_2d, 'is_price_abnormal'] = True

        abnormal_count = item_df['is_price_abnormal'].sum()
        if abnormal_count > 0:
            print(f"    ⚠️  物品 {good_id} 标记 {abnormal_count} 个异常价格日期")

        filtered_frames.append(item_df)

    if not filtered_frames:
        print("❌ 所有物品都被过滤！")
        return pd.DataFrame()

    result_df = pd.concat(filtered_frames, ignore_index=True)
    print(f"✅ 数据质量过滤完成:")
    print(f"  - 原始物品数: {total_items}")
    print(f"  - 排除低流动性物品: {excluded_items}")
    print(f"  - 保留物品数: {result_df['good_id'].nunique()}")
    print(f"  - 异常价格日期标记: {result_df['is_price_abnormal'].sum()} 个")
    return result_df

# =========================
# 特征计算（含点差/跨平台/动量 z-score/斜率）
# =========================
def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    def per_gid(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("date").copy()
        # 基础动量/波动
        for plat in PLATFORMS:
            ps = f"{plat}_sell_price"
            if ps not in g.columns:
                continue
            r = g[ps].pct_change()
            g[f"{plat}_ret_1d"]  = r
            g[f"{plat}_ret_7d"]  = g[ps] / g[ps].shift(MOM7_LAG)  - 1.0
            g[f"{plat}_ret_30d"] = g[ps] / g[ps].shift(MOM30_LAG) - 1.0
            g[f"{plat}_vol_14"]  = g[ps].pct_change().rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()

            # 点差
            bid = g.get(f"{plat}_buy_price")
            ask = g.get(f"{plat}_sell_price")
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2.0
                g[f"{plat}_spread"] = (ask - bid) / mid.replace(0, np.nan)

        # 跨平台价差/比率（BUFF vs YYYP）
        if set(["BUFF_sell_price", "YYYP_sell_price"]).issubset(g.columns):
            g["cross_diff"] = (g["BUFF_sell_price"] - g["YYYP_sell_price"]).abs()
            g["cross_ratio"] = (g["BUFF_sell_price"] / g["YYYP_sell_price"]).replace([np.inf, -np.inf], np.nan)

        # z-score 动量 + 3 日动量斜率
        for plat in PLATFORMS:
            if f"{plat}_vol_14" in g.columns:
                vol = g[f"{plat}_vol_14"] + 1e-9
                g[f"{plat}_r7_z"]  = g.get(f"{plat}_ret_7d", 0.0)  / vol
                g[f"{plat}_r30_z"] = g.get(f"{plat}_ret_30d", 0.0) / vol
                g[f"{plat}_r7_slope3"] = g.get(f"{plat}_ret_7d", pd.Series(index=g.index)).diff(3)

        return g

    out = out.groupby("good_id", group_keys=False).apply(per_gid)
    return out

# =========================
# 结构体
# =========================
@dataclass
class Position:
    platform: str
    qty: int
    buy_price: float
    buy_date: pd.Timestamp
    strat_id: str
    tp: float
    sl: float
    peak_ret: float = 0.0   # 跟踪止盈需要

@dataclass
class Trade:
    date: pd.Timestamp
    good_id: str
    item_name: str
    platform: str
    strat_id: str
    side: str
    price: float
    qty: int
    cash_after: float
    pnl_after_fee: float
    holding_days: int

# =========================
# 多臂（策略/平台）
# =========================
class EpsilonGreedyChooser:
    def __init__(self, keys: List[str],
                 eps_start=0.2, eps_end=0.02, decay_steps=365,
                 temp_start=0.8, temp_end=0.2, temp_decay_steps=365):
        self.keys = keys
        self.counts = {k: 0 for k in keys}
        self.rewards = {k: 0.0 for k in keys}
        self.ema = {k: 0.0 for k in keys}
        self.steps = 0
        self.eps_start = eps_start
        self.eps_end = eps_end
        self.decay_steps = decay_steps
        self.temp_start = temp_start
        self.temp_end = temp_end
        self.temp_decay_steps = temp_decay_steps

    def _epsilon(self):
        t = min(1.0, self.steps / max(1, self.decay_steps))
        return self.eps_start + (self.eps_end - self.eps_start) * t

    def _temperature(self):
        t = min(1.0, self.steps / max(1, self.temp_decay_steps))
        return self.temp_start + (self.temp_end - self.temp_start) * t

    def select(self) -> str:
        self.steps += 1
        if np.random.rand() < self._epsilon():
            return np.random.choice(self.keys)
        temp = max(1e-6, self._temperature())
        vals = np.array([self.ema[k] for k in self.keys]) / max(1e-9, temp)
        probs = np.exp(vals - vals.max()); probs /= probs.sum()
        return np.random.choice(self.keys, p=probs)

    def update(self, key: str, reward: float):
        self.counts[key] += 1
        self.rewards[key] += reward
        self.ema[key] = (1 - ALPHA_EMA) * self.ema[key] + ALPHA_EMA * reward

# =========================
# 打分（含点差/动量 z-score/三层记忆）
# =========================
def _z(v):
    return 0.0 if (v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))) else float(v)

def score_candidate(r1, r7, r30, vol, strat_ema, plat_ema, item_ema, spread, r7z, r30z) -> float:
    r1, r7, r30, vol = _z(r1), _z(r7), _z(r30), max(0.0, _z(vol))
    strat_ema, plat_ema, item_ema = _z(strat_ema), _z(plat_ema), _z(item_ema)
    spread = max(0.0, _z(spread))
    r7z, r30z = _z(r7z), _z(r30z)

    pos_dip1d = max(-r1, 0.0)
    spread_penalty = min(spread / 0.10, 1.0)  # 点差 0~10% → 0~1 惩罚
    score = (
        0.6 * r7z + 0.4 * r30z + 0.3 * pos_dip1d
        - 0.7 * max(vol, 0.0)
        - 0.8 * spread_penalty
        + 0.5 * strat_ema + 0.6 * plat_ema + 0.7 * item_ema
    )
    return float(score)

# =========================
# 主回测（含 T+7 强化）
# =========================
def adaptive_backtest(df: pd.DataFrame, init_state: Optional[Dict]=None):
    # 必要列防御
    need_cols = {
        "date","good_id",
        "BUFF_buy_price","BUFF_sell_price","BUFF_buy_num","BUFF_sell_num",
        "YYYP_buy_price","YYYP_sell_price","YYYP_buy_num","YYYP_sell_num",
        "BUFF_ret_1d","BUFF_ret_7d","BUFF_ret_30d","BUFF_vol_14",
        "YYYP_ret_1d","YYYP_ret_7d","YYYP_ret_30d","YYYP_vol_14",
        "cross_ratio"
    }
    for c in need_cols:
        if c not in df.columns:
            df[c] = np.nan

    # 过滤异常价格日期
    if 'is_price_abnormal' in df.columns:
        abnormal_count = df['is_price_abnormal'].sum()
        if abnormal_count > 0:
            print(f"🚫 回测中排除 {abnormal_count} 个异常价格日期")
            df = df[~df['is_price_abnormal']].copy()

    # 至少一个平台有有效卖价
    valid = (df["BUFF_sell_price"] >= MIN_PRICE) | (df["YYYP_sell_price"] >= MIN_PRICE)
    df = df[valid].copy().sort_values(["date","good_id"]).reset_index(drop=True)

    cash = INITIAL_CASH
    positions: Dict[Tuple[str,str], Position] = {}
    trades: List[Trade] = []
    equity_track = []
    last_buy_date: Dict[str, pd.Timestamp] = {}

    # 多臂
    strat_keys = [s[0] for s in STRATEGY_FAMILY]
    strat_map = {s[0]: s for s in STRATEGY_FAMILY}
    strat_chooser = EpsilonGreedyChooser(strat_keys, EPSILON_START, EPSILON_END, DECAY_STEPS,
                                         SOFTMAX_TEMP_START, SOFTMAX_TEMP_END, TEMP_DECAY_STEPS)
    plat_chooser  = EpsilonGreedyChooser(PLATFORMS, EPSILON_START, EPSILON_END, DECAY_STEPS,
                                         SOFTMAX_TEMP_START, SOFTMAX_TEMP_END, TEMP_DECAY_STEPS)

    # 按饰品的 ROI-EMA 记忆
    item_ema: Dict[str, float] = {}

    # 热启动
    if init_state is not None:
        try:
            if "strat" in init_state:
                for k,v in init_state["strat"].get("rewards_ema",{}).items():
                    if k in strat_chooser.ema: strat_chooser.ema[k] = float(v)
                for k,v in init_state["strat"].get("counts",{}).items():
                    if k in strat_chooser.counts: strat_chooser.counts[k] = int(v)
            if "plat" in init_state:
                for k,v in init_state["plat"].get("rewards_ema",{}).items():
                    if k in plat_chooser.ema: plat_chooser.ema[k] = float(v)
                for k,v in init_state["plat"].get("counts",{}).items():
                    if k in plat_chooser.counts: plat_chooser.counts[k] = int(v)
            if "item_ema" in init_state and isinstance(init_state["item_ema"], dict):
                for k,v in init_state["item_ema"].items():
                    item_ema[k] = float(v)
            print("🧠 已应用热启动 bandit/item 状态")
        except Exception as e:
            print("⚠️ 热启动状态解析失败，将忽略：", e)

    # ======== 按日推进 ========
    for day, day_df in df.groupby(df["date"].dt.date):
        day_ts = pd.to_datetime(str(day))

        # -------- 卖出：TP/SL/强平 + T+7 转弱与回撤 --------
        for (gid, plat), pos in list(positions.items()):
            row = day_df[day_df["good_id"] == gid]
            if row.empty:
                continue
            raw_sell = row.iloc[-1][f"{plat}_sell_price"]
            if not (pd.notna(raw_sell) and float(raw_sell) > 0):
                continue

            sell_price_eff = float(raw_sell) * (1.0 - SLIP_SELL)
            ret = sell_price_eff / pos.buy_price - 1.0
            holding = (day_ts - pos.buy_date).days

            # T+7 未达标不可卖
            if holding < MIN_HOLD_DAYS:
                # 同步峰值
                pos.peak_ret = max(pos.peak_ret, ret)
                continue

            do_sell, reason = False, ""

            # 达 7 天后的“转弱/回撤”退出
            r7z_now  = row.iloc[-1].get(f"{plat}_r7_z", np.nan)
            r30z_now = row.iloc[-1].get(f"{plat}_r30_z", np.nan)
            r1_now   = row.iloc[-1].get(f"{plat}_ret_1d", np.nan)
            weak_exit = (pd.notna(r7z_now) and r7z_now < 0.05 and pd.notna(r1_now) and r1_now < 0)

            pos.peak_ret = max(pos.peak_ret, ret)
            giveback = pos.peak_ret - ret
            trailed_exit = (pos.peak_ret >= 0.05 and giveback >= max(0.5*pos.tp, 0.02))  # 回撤一半TP或≥2%

            if weak_exit:
                do_sell, reason = True, "WEAK"
            if trailed_exit and not do_sell:
                do_sell, reason = True, "TB"

            # 常规 TP/SL/TIME
            if not do_sell:
                if ret >= pos.tp:               do_sell, reason = True, "TP"
                elif ret <= -pos.sl:            do_sell, reason = True, "SL"
                elif holding >= MAX_HOLD_DAYS:  do_sell, reason = True, "TIME"

            if do_sell and pos.qty > 0:
                proceeds = pos.qty * sell_price_eff * (1.0 - SELL_FEE_RATE)
                cash += proceeds
                pnl = pos.qty * sell_price_eff * (1.0 - SELL_FEE_RATE) - pos.qty * pos.buy_price

                notional_in = max(1e-9, pos.qty * pos.buy_price)
                roi = float(pnl) / notional_in

                strat_chooser.update(pos.strat_id, roi)
                plat_chooser.update(plat, roi)
                prev = item_ema.get(gid, 0.0)
                item_ema[gid] = (1 - ALPHA_EMA) * prev + ALPHA_EMA * roi

                item_name = day_df[day_df["good_id"] == gid]["item_name"].iloc[0] if not day_df[day_df["good_id"] == gid].empty else gid
                trades.append(Trade(day_ts, gid, item_name, plat, pos.strat_id,
                                    f"SELL({reason})", sell_price_eff, pos.qty, cash, float(pnl), int(holding)))
                del positions[(gid, plat)]
                continue

            # 没卖出也要同步峰值
            pos.peak_ret = max(pos.peak_ret, ret)

        # -------- 买入：先收集候选，再按 score 选 Top-K --------
        used_goods = set([g for (g,_) in positions.keys()])
        candidates: List[Tuple[float, dict]] = []

        for _, r in day_df.iterrows():
            gid = r["good_id"]
            if gid in used_goods:
                continue

            # 冷却
            last_t = last_buy_date.get(gid, None)
            if last_t is not None and (day_ts - last_t).days < COOLDOWN_DAYS_PER_GOOD:
                continue

            # 先随机/软策略选择，再验条件
            strat_id = strat_chooser.select()
            sid, dip1d, mom7, mom30, k_tp, k_sl, tp_min, sl_min = next(s for s in STRATEGY_FAMILY if s[0]==strat_id)
            plat = plat_chooser.select()

            pb = r.get(f"{plat}_buy_price")
            ps = r.get(f"{plat}_sell_price")
            r1  = r.get(f"{plat}_ret_1d")
            r7  = r.get(f"{plat}_ret_7d")
            r30 = r.get(f"{plat}_ret_30d")
            vol = r.get(f"{plat}_vol_14")
            sell_num_today = r.get(f"{plat}_sell_num", np.nan)
            buy_num_today  = r.get(f"{plat}_buy_num", np.nan)

            # 基本有效性
            if not (pd.notna(pb) and pd.notna(ps) and float(pb) > 0 and float(ps) > 0):
                continue
            if any(pd.isna(x) for x in [r1, r7, r30, vol]):
                continue
            if not ((sell_num_today >= MIN_SELL_NUM) and (buy_num_today >= MIN_BUY_NUM)):
                continue

            # 当日总成交笔数不应太低（防止恶意挂价）
            total_volume_today = ( (sell_num_today if pd.notna(sell_num_today) else 0)
                                 + (buy_num_today  if pd.notna(buy_num_today)  else 0) )
            if total_volume_today < 5:
                continue

            # 仅用历史信号触发
            if not ((r1 <= dip1d) and (r7 >= mom7) and (r30 >= mom30)):
                continue

            # ===== 入场硬条件（强过滤）=====
            mid = (float(pb) + float(ps)) / 2.0
            spread = (float(ps) - float(pb)) / (mid + 1e-9)
            if not np.isfinite(spread) or spread > 0.08:   # 点差 > 8% 放弃
                continue

            # 跨平台一致性：价格比率在 ±15% 内
            cross_ok = True
            if pd.notna(r.get("cross_ratio")):
                cr = float(r["cross_ratio"])
                if not (0.85 <= cr <= 1.18):
                    cross_ok = False
            if not cross_ok:
                continue

            # z-score 动量门槛
            r7z  = r.get(f"{plat}_r7_z", 0.0)
            r30z = r.get(f"{plat}_r30_z", 0.0)
            if (pd.isna(r7z) or r7z < 0.15) or (pd.isna(r30z) or r30z < 0.05):
                continue

            # 3 日动量斜率回升
            slope3 = r.get(f"{plat}_r7_slope3", 0.0)
            if pd.isna(slope3) or slope3 <= 0:
                continue

            # 平台 EMA 为负则加严入场
            plat_penalty = plat_chooser.ema.get(plat, 0.0)
            if plat_penalty < 0:
                if r7z < 0.25 or spread > 0.06:
                    continue

            # 动态 TP/SL（含绝对下限）
            tp = max(float(tp_min), float(k_tp) * float(vol))
            sl = max(float(sl_min), float(k_sl) * float(vol))

            # 预算与可买量
            if len(positions) >= MAX_POSITIONS:
                continue
            budget = min(cash * ORDER_FRACTION, NOTIONAL_CAP_PER_TRADE)
            pb_eff = float(pb) * (1.0 + SLIP_BUY)
            if budget < pb_eff:
                continue
            qty_budget = int(budget // pb_eff)

            qty_cap_by_book = np.inf
            if np.isfinite(sell_num_today):
                qty_cap_by_book = max(1, int(ALPHA_QTY_CAP * float(sell_num_today)))

            qty = max(0, min(qty_budget, qty_cap_by_book))
            if qty < MIN_QTY:
                continue

            s_ema = strat_chooser.ema.get(strat_id, 0.0)
            p_ema = plat_chooser.ema.get(plat, 0.0)
            i_ema = item_ema.get(gid, 0.0)
            score = score_candidate(r1, r7, r30, vol, s_ema, p_ema, i_ema, spread, r7z, r30z)

            candidates.append((
                score,
                {"gid": gid, "plat": plat, "strat_id": strat_id,
                 "tp": float(tp), "sl": float(sl), "pb_eff": float(pb_eff),
                 "qty": int(qty), "budget": float(budget)}
            ))

        # —— 只买 Top-K 候选（从高到低），受每日/并发约束 —— 
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            new_buys = 0
            for score, c in candidates:
                if new_buys >= MAX_NEW_BUYS_PER_DAY: break
                if len(positions) >= MAX_POSITIONS:  break
                gid = c["gid"]; plat = c["plat"]; strat_id = c["strat_id"]
                qty = c["qty"];  pb_eff = c["pb_eff"]; tp = c["tp"]; sl = c["sl"]

                if qty < MIN_QTY or pb_eff <= 0 or cash < qty * pb_eff:
                    continue

                # 执行买入
                cost = qty * pb_eff
                cash -= cost
                positions[(gid, plat)] = Position(plat, qty, pb_eff, day_ts, strat_id, tp, sl, peak_ret=0.0)
                last_buy_date[gid] = day_ts
                item_name = day_df[day_df["good_id"] == gid]["item_name"].iloc[0] if not day_df[day_df["good_id"] == gid].empty else gid
                trades.append(Trade(day_ts, gid, item_name, plat, strat_id, "BUY", pb_eff, qty, cash, 0.0, 0))
                new_buys += 1

        # —— 每日权益估值 —— 
        mv = 0.0
        if positions:
            for (gid, plat), pos in positions.items():
                row = day_df[day_df["good_id"] == gid]
                if row.empty:
                    continue
                cur = row.iloc[-1][f"{plat}_sell_price"]
                if pd.notna(cur) and float(cur) > 0:
                    mv += pos.qty * float(cur)
        equity_track.append((day_ts, cash + mv))

    # 期末 EOP 处理（T+7 与剩余市值）
    if positions:
        last_day = df["date"].max().normalize()
        remaining_positions = {}
        final_market_value = 0.0

        for (gid, plat), pos in list(positions.items()):
            holding = (last_day - pos.buy_date).days
            rows = df[df["good_id"] == gid]
            if rows.empty:
                continue
            final_raw = rows.iloc[-1][f"{plat}_sell_price"]
            if not (pd.notna(final_raw) and float(final_raw) > 0):
                continue

            current_mv = pos.qty * float(final_raw)

            if holding < MIN_HOLD_DAYS:
                print(f"⏳ 持仓 {gid}@{plat} 未满T+7（持有{holding}天），当前市值: {current_mv:.2f}元")
                remaining_positions[(gid, plat)] = pos
                final_market_value += current_mv
                continue

            sell_price_eff = float(final_raw) * (1.0 - SLIP_SELL)
            proceeds = pos.qty * sell_price_eff * (1.0 - SELL_FEE_RATE)
            cash += proceeds
            pnl = pos.qty * sell_price_eff * (1.0 - SELL_FEE_RATE) - pos.qty * pos.buy_price
            notional_in = max(1e-9, pos.qty * pos.buy_price)
            roi = float(pnl) / notional_in
            strat_chooser.update(pos.strat_id, roi)
            plat_chooser.update(plat, roi)
            prev = item_ema.get(gid, 0.0)
            item_ema[gid] = (1 - ALPHA_EMA) * prev + ALPHA_EMA * roi

            rows_for_name = df[df["good_id"] == gid]
            item_name = rows_for_name["item_name"].iloc[0] if not rows_for_name.empty else gid
            trades.append(Trade(last_day, gid, item_name, plat, pos.strat_id,
                                "SELL(EOP)", sell_price_eff, pos.qty, cash, float(pnl), int(holding)))
            del positions[(gid, plat)]

        positions = remaining_positions
        final_equity = cash + final_market_value
        equity_track.append((last_day, final_equity))

        if remaining_positions:
            print(f"📊 期末：现金 {cash:.2f}，剩余持仓市值 {final_market_value:.2f}，总权益 {final_equity:.2f}")
            print(f"🔒 保留 {len(remaining_positions)} 个未满T+7持仓")
        else:
            print(f"📊 期末：全部持仓已平，现金 {cash:.2f}")
    else:
        last_day = df["date"].max().normalize()
        equity_track.append((last_day, cash))

    # 汇总
    trades_df = pd.DataFrame([asdict(t) for t in trades])
    equity = pd.Series([e for _,e in equity_track], index=[d for d,_ in equity_track]).sort_index()

    sell_trades = trades_df[trades_df["side"].str.startswith("SELL")]
    wins = int((sell_trades["pnl_after_fee"] > 0).sum())
    total_pnl = float(sell_trades["pnl_after_fee"].sum()) if not sell_trades.empty else 0.0
    avg_pnl = float(sell_trades["pnl_after_fee"].mean()) if not sell_trades.empty else 0.0

    roll_peak = equity.cummax()
    dd = (equity - roll_peak) / roll_peak.replace(0, np.nan)
    max_dd = float(dd.min()) if len(dd) else 0.0

    final_equity = float(equity.iloc[-1]) if len(equity) > 0 else float(cash)
    summary = {
        "final_cash": float(cash),
        "final_equity": final_equity,
        "remaining_positions": int(len(positions)),
        "trades": int(len(sell_trades)),
        "wins": wins,
        "win_rate": float(wins / max(1, len(sell_trades))),
        "avg_pnl_per_trade": avg_pnl,
        "total_pnl": total_pnl,
        "max_drawdown": max_dd,
    }
    strat_panel = {
        "counts": {k:int(v) for k,v in strat_chooser.counts.items()},
        "rewards_sum": {k:float(v) for k,v in strat_chooser.rewards.items()},
        "rewards_ema": {k:float(v) for k,v in strat_chooser.ema.items()},
    }
    plat_panel = {
        "counts": {k:int(v) for k,v in plat_chooser.counts.items()},
        "rewards_sum": {k:float(v) for k,v in plat_chooser.rewards.items()},
        "rewards_ema": {k:float(v) for k,v in plat_chooser.ema.items()},
    }
    return summary, trades_df, equity, strat_panel, plat_panel, item_ema

# =========================
# 主入口：训练 + 测试（连续在线）
# =========================
def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--run_index", type=int, default=1)
    parser.add_argument("--state_path", type=str, default=None)
    args = parser.parse_args()

    cutoff = resolve_cutoff_date()
    if args.seed is None:
        auto_seed = int((int(datetime.now().strftime("%Y%m%d")) * 10 + args.run_index) % 2**31)
    else:
        auto_seed = args.seed
    np.random.seed(auto_seed); random.seed(auto_seed)

    print(f"🕒 测试区间截断到（含）{cutoff.date()}  seed={auto_seed}")
    print(f"📂 加载数据：{DATA_DIR}")
    raw = load_all_items(DATA_DIR)
    print(f"✅ 读取：{raw['good_id'].nunique()} 个商品，{len(raw):,} 条记录，时间 {raw['date'].min().date()} ~ {raw['date'].max().date()}")

    print("🧮 数据质量过滤...")
    filtered = filter_data_quality(raw)

    print("🧮 计算特征（1/7/30，vol14，spread/cross/z-score/slope）...")
    feat = compute_features(filtered)

    feat_train = feat[(feat["date"] >= pd.to_datetime(TRAIN_START)) & (feat["date"] <= pd.to_datetime(TRAIN_END))].copy()
    feat_test  = feat[(feat["date"] >= pd.to_datetime(TEST_START)) & (feat["date"] <= cutoff)].copy()

    preload_state = None
    if args.state_path and os.path.exists(args.state_path):
        try:
            with open(args.state_path, "r", encoding="utf-8") as f:
                preload_state = json.load(f)
            print(f"🧠 已加载状态：{args.state_path}")
        except Exception as e:
            print("⚠️ 状态读取失败：", e)

    print("\n🔧 训练期（在线自适应） 2023-01-01 ~ 2024-12-31 ...")
    train_summary, train_trades, train_equity, train_strat_panel, train_plat_panel, train_item_ema = adaptive_backtest(
        feat_train, init_state=preload_state
    )
    print("📈 训练期表现：")
    for k,v in train_summary.items():
        if k == "final_equity":
            roi_pct = (v / INITIAL_CASH - 1) * 100
            print(f"  - {k}: {v:.2f} (ROI: {roi_pct:+.2f}%)")
        elif k in ["final_cash", "total_pnl", "avg_pnl_per_trade"]:
            print(f"  - {k}: {v:.2f}")
        elif k in ["win_rate", "max_drawdown"]:
            print(f"  - {k}: {v:.4f}")
        else:
            print(f"  - {k}: {v}")

    # 保存训练期文件
    results_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "results")
    os.makedirs(results_dir, exist_ok=True)
    train_trades.to_csv(os.path.join(results_dir, "trades_training_adaptive.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame({"date": train_equity.index, "equity": train_equity.values}).to_csv(
        os.path.join(results_dir, "equity_training_adaptive.csv"), index=False, encoding="utf-8-sig"
    )

    print(f"\n🧪 测试期（继续在线） 2025-01-01 ~ {cutoff.date()} ...")
    test_summary, test_trades, test_equity, test_strat_panel, test_plat_panel, test_item_ema = adaptive_backtest(
        feat_test, init_state={"strat": train_strat_panel, "plat": train_plat_panel, "item_ema": train_item_ema}
    )
    print("📊 测试期表现：")
    for k,v in test_summary.items():
        if k == "final_equity":
            roi_pct = (v / INITIAL_CASH - 1) * 100
            print(f"  - {k}: {v:.2f} (ROI: {roi_pct:+.2f}%)")
        elif k in ["final_cash", "total_pnl", "avg_pnl_per_trade"]:
            print(f"  - {k}: {v:.2f}")
        elif k in ["win_rate", "max_drawdown"]:
            print(f"  - {k}: {v:.4f}")
        else:
            print(f"  - {k}: {v}")

    test_trades.to_csv(os.path.join(results_dir, "trades_test_adaptive.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame({"date": test_equity.index, "equity": test_equity.values}).to_csv(
        os.path.join(results_dir, "equity_test_adaptive.csv"), index=False, encoding="utf-8-sig"
    )

    print("\n🗂️ 面板（累计）：")
    print("  策略使用次数（训练）：", train_strat_panel["counts"])
    print("  策略EMA回报（训练）：", {k: round(v,4) for k,v in train_strat_panel["rewards_ema"].items()})
    print("  平台使用次数（训练）：", train_plat_panel["counts"])
    print("  平台EMA回报（训练）：", {k: round(v,4) for k,v in train_plat_panel["rewards_ema"].items()})
    print("  平台使用次数（测试）：", test_plat_panel["counts"])
    print("  平台EMA回报（测试）：", {k: round(v,4) for k,v in test_plat_panel["rewards_ema"].items()})

    # Top5 交易最多的饰品
    for tag, tdf in [("训练", train_trades), ("测试", test_trades)]:
        if not tdf.empty:
            top_items = tdf[tdf["side"]=="BUY"]["item_name"].value_counts().head(5)
            print(f"\n🔎 {tag}期交易最多的饰品 Top5：")
            for name, cnt in top_items.items():
                print(f"  - {name}: {cnt} 笔买入")

    print(f"\n⚙️ 关键参数：每日最多新开仓 {MAX_NEW_BUYS_PER_DAY}，并发上限 {MAX_POSITIONS}。")
    print(f"🔒 T+{MIN_HOLD_DAYS} 交易机制：买入后最少持有 {MIN_HOLD_DAYS} 天；最长 {MAX_HOLD_DAYS} 天强制平仓。")
    print(f"💰 手续费：{SELL_FEE_RATE*100:.1f}%；滑点：买 {SLIP_BUY*100:.1f}% / 卖 {SLIP_SELL*100:.1f}%。")
    print(f"🧼 数据过滤：排除平均交易量<{MIN_AVG_VOLUME} 的物品；剔除 >{MAX_DAILY_PRICE_CHANGE*100:.0f}% 的异常价格日期。")
    print("🧼 0 价格视为缺失；Top-K 选股启用（含策略/平台/饰品三层在线记忆，点差/跨平台一致性约束）。")

    # 保存热启动状态（包含 item_ema）
    if args.state_path:
        try:
            state_to_save = {
                "strat": test_strat_panel,
                "plat": test_plat_panel,
                "item_ema": test_item_ema
            }
            with open(args.state_path, "w", encoding="utf-8") as f:
                json.dump(state_to_save, f, ensure_ascii=False, indent=2)
            print(f"💾 已保存状态：{args.state_path}")
        except Exception as e:
            print("⚠️ 状态保存失败：", e)

if __name__ == "__main__":
    run()