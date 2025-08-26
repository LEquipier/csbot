# -*- coding: utf-8 -*-
"""
T+7 实时选品 + 持仓跟踪与卖出建议（BUFF & YYYP）
- 目录：backend/Model/dataset/匕首/<刀型>/<物品>.csv
- CSV 至少包含：
  date, BUFF_sell_price, YYYP_sell_price, BUFF_buy_price, YYYP_buy_price,
  BUFF_sell_num, YYYP_sell_num, BUFF_buy_num, YYYP_buy_num, good_id
- 小时级别数据：自动用小时序列，分钟无严格要求
- 三档模式：稳健 / 适中 / 激进（阈值、TP/SL、回撤止盈均不同）
- 支持记录买入，持久化到 backend/state/positions.json；每次运行会更新持仓峰值、T+7 到期、卖出信号等
- 输出：打印摘要 + 写入 backend/results/realtime_reco.json + 历史记录 backend/results/history/

用法：
  分析：python backend/realtime_picker_t7.py --root Model/dataset/匕首 --mode 适中 --topk 8 --lookback 336
  记买：python backend/realtime_picker_t7.py --record-buy --knife 蝴蝶刀 --item "<文件名>.csv" --platform BUFF --qty 2 --price 27500 --time "2025-08-22 13:54"
  列仓：python backend/realtime_picker_t7.py --list-positions
"""

import os
import sys
import json
import glob
import math
import argparse
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# -------------------------
# 常量与路径
# -------------------------
PLATFORMS = ["BUFF", "YYYP"]
BACKEND_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BACKEND_DIR / "results" / "realtime_reco.json"
HISTORY_DIR = BACKEND_DIR / "results" / "history"
STATE_DIR = BACKEND_DIR / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
POSITIONS_PATH = STATE_DIR / "positions.json"   # 持仓状态
MIN_HOLD_DAYS = 7  # T+7：至少持有 7 天才能卖

# 平台费用（默认：卖出 2%，买入 0%）
PLATFORM_FEES = {
    "BUFF": {"buy": 0.00, "sell": 0.02},
    "YYYP": {"buy": 0.00, "sell": 0.02},
}

BASE_COLS = [
    "date",
    "BUFF_sell_price","YYYP_sell_price",
    "BUFF_buy_price","YYYP_buy_price",
    "BUFF_sell_num","YYYP_sell_num",
    "BUFF_buy_num","YYYP_buy_num",
    "good_id",
]

# -------------------------
# 工具函数
# -------------------------
def safe_num(x):
    try:
        v = float(x)
        if math.isfinite(v): return v
    except Exception:
        pass
    return np.nan

def pct_change(a, b):
    if b is None or not math.isfinite(b) or b == 0: return np.nan
    return a / b - 1.0

def rolling_mean(s: pd.Series, w: int):
    if s is None: return None
    try:
        return s.rolling(w, min_periods=w).mean()
    except Exception:
        return None

def last_valid(series: pd.Series):
    return series.dropna().iloc[-1] if (series is not None and len(series.dropna())>0) else np.nan

def cleanup_old_history_files():
    """清理30天前的历史文件"""
    try:
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=30)
        
        for history_file in HISTORY_DIR.glob("reco_*.json"):
            try:
                # 从文件名提取时间戳
                timestamp_str = history_file.stem.split("_", 1)[1]  # reco_20250101_120000 -> 20250101_120000
                file_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if file_date < cutoff_date:
                    history_file.unlink()
                    print(f"已删除旧历史文件: {history_file.name}")
            except Exception as e:
                print(f"处理历史文件 {history_file.name} 时出错: {e}")
    except Exception as e:
        print(f"清理历史文件时出错: {e}")

def net_return(sell_price: float, buy_price: float, plat: str) -> float:
    """考虑平台费的净收益：卖出扣费、买入不加费（默认 0%）"""
    fees = PLATFORM_FEES.get(plat, {"buy":0.0, "sell":0.0})
    net_sell = sell_price * (1 - float(fees.get("sell", 0.0)))
    net_buy  = buy_price  * (1 + float(fees.get("buy",  0.0)))
    if net_buy <= 0 or not math.isfinite(net_buy): 
        return 0.0
    return net_sell / net_buy - 1.0

# -------------------------
# 三档参数
# -------------------------
@dataclass
class ModeCfg:
    name: str
    min_hours: int            # 最小历史小时数
    ma_fast: int
    ma_mid: int
    ma_long: int
    max_spread: float         # (ask-bid)/mid
    cross_ratio_low: float
    cross_ratio_high: float
    min_liq_ratio: float      # 今日/24h均值
    min_fast_over_mid: float
    min_mid_over_long: float
    need_mid_slope_pos: bool
    # 打分权重
    w_fast_mom: float
    w_long_trend: float
    w_liq_ratio: float
    w_cross_neutral: float
    w_spread_penalty: float
    # 观察名单放宽
    watch_relax: float
    # TP/SL 与回撤（用于持仓卖出判定）
    tp_abs: float             # 绝对止盈阈值
    sl_abs: float             # 绝对止损阈值
    trail_trigger: float      # 启动跟踪止盈所需峰值收益
    trail_giveback: float     # 回撤多少触发（例如 0.5 表示回吐 50% 峰值）
    # 每轮最多返回的买入候选数（最终还会被 --topk 限制一次）
    daily_topk_cap: int

CFG_CONSERVATIVE = ModeCfg(
    name="稳健",
    min_hours=168, ma_fast=6, ma_mid=24, ma_long=168,
    max_spread=0.06, cross_ratio_low=0.92, cross_ratio_high=1.08,
    min_liq_ratio=1.2, min_fast_over_mid=0.004, min_mid_over_long=0.010,
    need_mid_slope_pos=True,
    w_fast_mom=1.2, w_long_trend=1.4, w_liq_ratio=1.0, w_cross_neutral=1.0, w_spread_penalty=1.6,
    watch_relax=1.15,
    tp_abs=0.05, sl_abs=0.03, trail_trigger=0.05, trail_giveback=0.5,
    daily_topk_cap=5
)
CFG_MODERATE = ModeCfg(
    name="适中",
    # ★ 改动：把 min_hours 从 72 提升到 168，与 ma_long=168 对齐，避免“看起来够72h但过不了硬条件”的错觉
    min_hours=168, ma_fast=6, ma_mid=24, ma_long=168,
    max_spread=0.08, cross_ratio_low=0.90, cross_ratio_high=1.12,
    min_liq_ratio=1.0, min_fast_over_mid=0.0, min_mid_over_long=0.002,
    need_mid_slope_pos=False,
    w_fast_mom=1.1, w_long_trend=1.2, w_liq_ratio=0.9, w_cross_neutral=0.8, w_spread_penalty=1.2,
    watch_relax=1.20,
    tp_abs=0.06, sl_abs=0.04, trail_trigger=0.06, trail_giveback=0.55,
    daily_topk_cap=8
)
CFG_AGGRESSIVE = ModeCfg(
    name="激进",
    min_hours=24, ma_fast=4, ma_mid=12, ma_long=72,
    max_spread=0.10, cross_ratio_low=0.85, cross_ratio_high=1.15,
    min_liq_ratio=0.8, min_fast_over_mid=-0.002, min_mid_over_long=-0.005,
    need_mid_slope_pos=False,
    w_fast_mom=1.2, w_long_trend=0.8, w_liq_ratio=0.8, w_cross_neutral=0.6, w_spread_penalty=0.8,
    watch_relax=1.30,
    tp_abs=0.08, sl_abs=0.05, trail_trigger=0.07, trail_giveback=0.6,
    daily_topk_cap=12
)

MODE_MAP = {"稳健": CFG_CONSERVATIVE, "适中": CFG_MODERATE, "激进": CFG_AGGRESSIVE}

# -------------------------
# 读取单 CSV（lookback 内）
# -------------------------
def read_item_csv(fp: Path, lookback_hours: int) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(fp, encoding="utf-8")
    except Exception:
        df = pd.read_csv(fp, encoding="gbk")

    if "date" not in df.columns and "data" in df.columns:
        df = df.rename(columns={"data": "date"})

    for c in BASE_COLS:
        if c not in df.columns:
            df[c] = np.nan

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.sort_values("date").reset_index(drop=True)

    if lookback_hours and len(df):
        cutoff = df["date"].max() - pd.Timedelta(hours=lookback_hours)
        df = df[df["date"] >= cutoff].copy()

    for p in PLATFORMS:
        for col in [f"{p}_sell_price", f"{p}_buy_price",
                    f"{p}_sell_num",  f"{p}_buy_num"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    for p in PLATFORMS:
        for col in [f"{p}_sell_price", f"{p}_buy_price"]:
            if col in df.columns:
                df.loc[df[col] == 0.0, col] = np.nan

    return df if len(df) else None

# -------------------------
# 技术指标（用于 80% 预警）
# -------------------------
def _ema(series: pd.Series, span: int):
    if series is None: return None
    try:
        return series.ewm(span=span, adjust=False, min_periods=span).mean()
    except Exception:
        return None

def _rsi(series: pd.Series, period: int = 14):
    s = pd.to_numeric(series, errors="coerce")
    delta = s.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = -delta.clip(upper=0).rolling(period).mean()
    rs = up / down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _bollinger(series: pd.Series, n: int = 20, k: float = 2.0):
    m = series.rolling(n).mean()
    sd = series.rolling(n).std()
    upper, lower = m + k*sd, m - k*sd
    pctb = (series - lower) / (upper - lower)
    return m, upper, lower, pctb

def compute_indicators(df: pd.DataFrame, plat: str):
    """基于中价计算 EMA、RSI、布林带%b、ATR(简化)"""
    ask = df.get(f"{plat}_sell_price")
    bid = df.get(f"{plat}_buy_price")
    if ask is None and bid is None: 
        return None
    mid = (ask + bid) / 2.0 if (ask is not None and bid is not None) else (ask if ask is not None else bid)
    mid = pd.to_numeric(mid, errors="coerce")

    ema_fast = _ema(mid, 6)
    ema_mid  = _ema(mid, 24)
    ema_long = _ema(mid, 72)
    rsi14 = _rsi(mid, 14)
    _, _, _, bb_pctb = _bollinger(mid, 20, 2.0)

    # ATR 简化：用绝对变化的EMA近似
    atr = mid.diff().abs().ewm(span=14, adjust=False).mean()

    latest = lambda s: (float(s.dropna().iloc[-1]) if (s is not None and len(s.dropna())) else np.nan)
    return {
        "ema_fast": latest(ema_fast),
        "ema_mid":  latest(ema_mid),
        "ema_long": latest(ema_long),
        "rsi14":    latest(rsi14),
        "bb_pctb":  latest(bb_pctb),
        "atr":      latest(atr),
        "mid":      latest(mid),
    }

def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0

def estimate_add_reduce_prob(s, inds: dict, cr: float) -> tuple:
    """
    返回 (add_prob, reduce_prob, add_reasons, reduce_reasons)
    以规则打分 + Sigmoid 映射到[0,1]，仅用于触发型预警。
    """
    add_score = 0.0; reduce_score = 0.0
    add_r = []; red_r = []

    # 1) 均线关系（多空顺序）
    if all(pd.notna([s.ma_fast, s.ma_mid, s.ma_long])):
        if s.ma_fast >= s.ma_mid >= s.ma_long:
            add_score += 1.2; add_r.append("均线多头排列")
        if s.ma_fast <= s.ma_mid <= s.ma_long:
            reduce_score += 1.0; red_r.append("均线空头排列")

    # 2) 短期动量 & 中期趋势
    if pd.notna(s.fast_over_mid):
        if s.fast_over_mid > 0: add_score += min(s.fast_over_mid*20, 1.0)
        else: reduce_score += min(abs(s.fast_over_mid)*16, 1.0)
    if pd.notna(s.mid_over_long):
        if s.mid_over_long > 0: add_score += min(s.mid_over_long*10, 1.0)
        else: reduce_score += min(abs(s.mid_over_long)*10, 1.0)

    # 3) RSI（动量/超买超卖）
    rsi = inds.get("rsi14")
    if pd.notna(rsi):
        if rsi < 32: 
            add_score += 0.8; add_r.append(f"RSI超卖({rsi:.1f})")
        elif rsi > 68:
            reduce_score += 0.8; red_r.append(f"RSI超买({rsi:.1f})")

    # 4) 布林带 %b
    bb = inds.get("bb_pctb")
    if pd.notna(bb):
        if bb <= 0.1: 
            add_score += 0.6; add_r.append("贴近下轨")
        elif bb >= 0.9:
            reduce_score += 0.6; red_r.append("贴近上轨")

    # 5) 点差与流动性
    if pd.notna(s.spread):
        if s.spread <= 0.04: add_score += 0.3
        if s.spread >= 0.10: reduce_score += 0.5; red_r.append(f"点差偏宽({s.spread:.2%})")
    if pd.notna(s.liq_ratio_24h):
        if s.liq_ratio_24h >= 1.2: add_score += 0.3
        if s.liq_ratio_24h < 0.8:  reduce_score += 0.4; red_r.append("流动性转弱")

    # 6) 跨平台一致性
    if pd.notna(cr):
        devi = abs(cr-1.0)
        if devi <= 0.02: add_score += 0.3
        if devi >= 0.08: reduce_score += 0.4; red_r.append(f"跨平台偏离({cr:.3f})")

    # 7) 互斥抑制
    add_prob = _sigmoid(add_score - 0.5*reduce_score)
    reduce_prob = _sigmoid(reduce_score - 0.5*add_score)

    return add_prob, reduce_prob, add_r, red_r

# -------------------------
# 计算平台特征 & 评分
# -------------------------
@dataclass
class PlatformSnapshot:
    platform: str
    price_sell: float
    price_buy: float
    spread: float
    liq_today: float
    liq_ratio_24h: float
    ma_fast: float
    ma_mid: float
    ma_long: float
    fast_over_mid: float
    mid_over_long: float
    mid_slope_6h: float  # 中线近 6h 斜率

def compute_platform_snapshot(df: pd.DataFrame, plat: str, cfg: ModeCfg) -> Optional[PlatformSnapshot]:
    ask = df.get(f"{plat}_sell_price")
    bid = df.get(f"{plat}_buy_price")
    sell_num = df.get(f"{plat}_sell_num")
    buy_num  = df.get(f"{plat}_buy_num")
    if ask is None and bid is None: return None

    mid = (ask + bid) / 2.0 if (ask is not None and bid is not None) else (ask if ask is not None else bid)

    ma_fast = rolling_mean(mid, cfg.ma_fast)
    ma_mid  = rolling_mean(mid, cfg.ma_mid)
    ma_long = rolling_mean(mid, cfg.ma_long)

    mid_slope_6h = np.nan
    if ma_mid is not None and len(ma_mid.dropna()) >= 6:
        a = ma_mid.iloc[-1]; b = ma_mid.iloc[-6]
        base = b if (pd.notna(b) and b != 0) else np.nan
        mid_slope_6h = pct_change(a, base)

    liq_today = np.nan
    if sell_num is not None or buy_num is not None:
        s = sell_num.iloc[-1] if (sell_num is not None and len(sell_num)) else 0
        b = buy_num.iloc[-1]  if (buy_num  is not None and len(buy_num))  else 0
        liq_today = safe_num(s) + safe_num(b)

    liq_24h = np.nan
    if sell_num is not None and buy_num is not None:
        liq_series = pd.to_numeric(sell_num, errors="coerce").fillna(0) + \
                     pd.to_numeric(buy_num,  errors="coerce").fillna(0)
        liq_24h_series = rolling_mean(liq_series, 24)
        liq_24h = last_valid(liq_24h_series)
    liq_ratio = np.nan
    if pd.notna(liq_today) and pd.notna(liq_24h) and liq_24h > 0:
        liq_ratio = liq_today / liq_24h

    spread = np.nan
    if ask is not None and bid is not None:
        a = ask.iloc[-1]; b = bid.iloc[-1]
        mid_last = (a + b) / 2.0 if (pd.notna(a) and pd.notna(b)) else np.nan
        if pd.notna(a) and pd.notna(b) and pd.notna(mid_last) and mid_last>0:
            spread = (a - b) / mid_last

    fast_over_mid = pct_change(last_valid(ma_fast), last_valid(ma_mid))
    mid_over_long = pct_change(last_valid(ma_mid), last_valid(ma_long))

    return PlatformSnapshot(
        platform=plat,
        price_sell=safe_num(ask.iloc[-1]) if ask is not None and len(ask) else np.nan,
        price_buy=safe_num(bid.iloc[-1]) if bid is not None and len(bid) else np.nan,
        spread=safe_num(spread),
        liq_today=safe_num(liq_today),
        liq_ratio_24h=safe_num(liq_ratio),
        ma_fast=safe_num(last_valid(ma_fast)),
        ma_mid=safe_num(last_valid(ma_mid)),
        ma_long=safe_num(last_valid(ma_long)),
        fast_over_mid=safe_num(fast_over_mid),
        mid_over_long=safe_num(mid_over_long),  # ★ 去掉二次 safe_num
        mid_slope_6h=safe_num(mid_slope_6h),
    )

def cross_ratio_now(df: pd.DataFrame) -> float:
    b = df.get("BUFF_sell_price"); y = df.get("YYYP_sell_price")
    if b is None or y is None or len(b)==0 or len(y)==0: return np.nan
    bb, yy = b.iloc[-1], y.iloc[-1]
    if pd.notna(bb) and pd.notna(yy) and yy>0: return float(bb)/float(yy)
    return np.nan

def score_item(s: PlatformSnapshot, cr: float, cfg: ModeCfg) -> float:
    fast = max(s.fast_over_mid, 0.0) if pd.notna(s.fast_over_mid) else 0.0
    trend = max(s.mid_over_long, 0.0) if pd.notna(s.mid_over_long) else 0.0
    liq = s.liq_ratio_24h if pd.notna(s.liq_ratio_24h) else 0.0
    cross_neutral = 0.0
    if pd.notna(cr) and cr>0:
        cross_neutral = 1.0 - min(abs(cr - 1.0), 0.3)/0.3
    spread_penalty = 0.0
    if pd.notna(s.spread) and s.spread > 0:
        spread_penalty = min(s.spread / 0.10, 1.0)
    return (
        cfg.w_fast_mom * fast
        + cfg.w_long_trend * trend
        + cfg.w_liq_ratio * liq
        + cfg.w_cross_neutral * cross_neutral
        - cfg.w_spread_penalty * spread_penalty
    )

# -------------------------
# 入场硬条件 / 观察名单
# -------------------------
def passes_buy_hard_filters(s: PlatformSnapshot, cr: float, cfg: ModeCfg, relax: float = 1.0) -> Tuple[bool, List[str]]:
    reasons = []; ok = True
    if pd.isna(s.spread) or s.spread > cfg.max_spread * relax:
        ok = False; reasons.append(f"点差过宽({s.spread:.3f})")
    if pd.notna(cr):
        low = cfg.cross_ratio_low / relax
        high = cfg.cross_ratio_high * relax
        if not (low <= cr <= high):
            ok = False; reasons.append(f"跨平台偏离({cr:.3f})")
    if pd.isna(s.liq_ratio_24h) or s.liq_ratio_24h < (cfg.min_liq_ratio / relax):
        ok = False; reasons.append(f"流动性不足(ratio {s.liq_ratio_24h:.2f})")
    if pd.isna(s.fast_over_mid) or s.fast_over_mid < (cfg.min_fast_over_mid / relax):
        ok = False; reasons.append(f"短期动量弱({s.fast_over_mid:.3f})")
    if pd.isna(s.mid_over_long) or s.mid_over_long < (cfg.min_mid_over_long / relax):
        ok = False; reasons.append(f"中期趋势弱({s.mid_over_long:.3f})")
    if cfg.need_mid_slope_pos:
        if pd.isna(s.mid_slope_6h) or s.mid_slope_6h <= 0:
            ok = False; reasons.append("中线斜率不升")
    return ok, reasons

def makes_sell_alert_for_snapshot(s: PlatformSnapshot, cfg: ModeCfg) -> Tuple[bool, List[str]]:
    cond = []
    if pd.notna(s.fast_over_mid) and s.fast_over_mid < 0: cond.append("快线下穿中线")
    if pd.notna(s.mid_slope_6h) and s.mid_slope_6h < 0:   cond.append("中线走弱")
    if pd.notna(s.spread) and s.spread > cfg.max_spread * 1.5: cond.append("点差急剧走宽")
    if pd.notna(s.liq_ratio_24h) and s.liq_ratio_24h < 0.6:    cond.append("流动性骤降")
    return (len(cond)>0), cond

# -------------------------
# 诊断：输出数据覆盖情况
# -------------------------
def log_series_coverage(knife_type: str, fp: Path, df: pd.DataFrame, cfg: ModeCfg):
    try:
        if df is None or len(df) == 0:
            print(f"[诊断] {knife_type}/{fp.name}: 无数据")
            return
        hours = int((df["date"].max() - df["date"].min()) / pd.Timedelta(hours=1)) + 1
        has_ma_long = len(df) >= cfg.ma_long
        has_liq_24h = len(df) >= 24
        print(f"[诊断] {knife_type}/{fp.name}: 有效小时={hours}h | 满足ma_long({cfg.ma_long})={has_ma_long} | 满足24h={has_liq_24h}")
    except Exception:
        pass

# -------------------------
# 持仓状态（持久化）
# -------------------------
def load_positions() -> List[dict]:
    if POSITIONS_PATH.exists():
        try:
            with open(POSITIONS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list): return data
        except Exception:
            pass
    return []

def save_positions(positions: List[dict]):
    POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)

def record_buy(knife: str, item_file: str, platform: str, qty: int, price: float, time_str: str, root_dir: Path):
    # 推断 good_id & item_name
    item_csv = (root_dir / knife / item_file)
    if not item_csv.exists():
        print(f"❌ 未找到物品 CSV：{item_csv}")
        sys.exit(2)
    try:
        df = pd.read_csv(item_csv, encoding="utf-8")
    except Exception:
        df = pd.read_csv(item_csv, encoding="gbk")
    gid = None
    if "good_id" in df.columns and len(df["good_id"].dropna()):
        gid = str(df["good_id"].dropna().iloc[-1])
    else:
        gid = Path(item_file).stem  # 兜底
    pos = {
        "knife_type": knife,
        "item_file": item_file,      # 用文件名定位
        "item_name": Path(item_file).stem,
        "good_id": gid,
        "platform": platform,
        "qty": int(qty),
        "buy_price": float(price),
        "buy_time": time_str,        # "2025-08-22 13:54"
        "peak_ret": 0.0              # 持续更新
    }
    positions = load_positions()
    positions.append(pos)
    save_positions(positions)
    print(f"✅ 已记录买入：{pos}")

def list_positions():
    positions = load_positions()
    if not positions:
        print("（当前无已记录的持仓）")
        return
    print("当前持仓：")
    for i,p in enumerate(positions,1):
        print(f"{i:>2}. [{p['platform']}] {p['knife_type']} / {p['item_name']} | 数量:{p['qty']} | 买价:{p['buy_price']} | 买时:{p['buy_time']} | 峰值:{p.get('peak_ret',0.0):+.3f}")

# -------------------------
# 主分析流程
# -------------------------
def analyze_root(root_dir: Path, mode_name: str, topk: int, lookback_hours: int):
    if mode_name not in MODE_MAP:
        raise ValueError(f"未知模式：{mode_name}，可选：{list(MODE_MAP.keys())}")
    cfg = MODE_MAP[mode_name]

    # 收集 csv
    csv_files = []
    for knife_dir in sorted(root_dir.glob("*")):
        if knife_dir.is_dir():
            for fp in sorted(knife_dir.glob("*.csv")):
                csv_files.append((knife_dir.name, fp))
    if not csv_files:  # 兼容深层
        for fp in root_dir.rglob("*.csv"):
            if fp.is_file():
                csv_files.append((fp.parent.name, fp))

    buy_list, watch_list = [], []
    sell_alerts_for_holdings, locked_until_t7 = [], []
    insufficient = []
    skipped = 0
    latest_ts = None

    # 读取持仓
    positions = load_positions()

    # 为快速检索，建立索引： {(knife_type, item_file)->df}
    cache_df: Dict[Tuple[str,str], pd.DataFrame] = {}

    # 遍历所有商品用于“买入候选 / 观察名单”
    for knife_type, fp in csv_files:
        df = read_item_csv(fp, lookback_hours)

        # 诊断日志：打印有效时长与是否满足 ma_long / 24h
        if df is not None and len(df):
            log_series_coverage(knife_type, fp, df, cfg)

        if df is None or len(df) < cfg.min_hours:
            insufficient.append(fp.name); 
            continue

        cur_ts = df["date"].max()
        if latest_ts is None or cur_ts > latest_ts: latest_ts = cur_ts

        cr = cross_ratio_now(df)
        for p in PLATFORMS:
            snap = compute_platform_snapshot(df, p, cfg)
            if snap is None or pd.isna(snap.price_sell): continue

            # 计算指标与 80% 预警概率
            inds = compute_indicators(df, p)
            add_prob = reduce_prob = None
            add_reasons = []; reduce_reasons = []
            if inds:
                add_prob, reduce_prob, add_reasons, reduce_reasons = estimate_add_reduce_prob(snap, inds, cr)

            ok_buy, why = passes_buy_hard_filters(snap, cr, cfg, relax=1.0)
            ok_watch, _ = passes_buy_hard_filters(snap, cr, cfg, relax=cfg.watch_relax)
            score = score_item(snap, cr, cfg)

            details = {
                "knife_type": knife_type,   # 保持字段名不变（向后兼容）
                "item_name": fp.stem,
                "platform": p,
                "price_sell": round(snap.price_sell,4) if pd.notna(snap.price_sell) else None,
                "price_buy": round(snap.price_buy,4) if pd.notna(snap.price_buy) else None,
                "spread": round(snap.spread,4) if pd.notna(snap.spread) else None,
                "liq_ratio_24h": round(snap.liq_ratio_24h,3) if pd.notna(snap.liq_ratio_24h) else None,
                "fast_over_mid": round(snap.fast_over_mid,4) if pd.notna(snap.fast_over_mid) else None,
                "mid_over_long": round(snap.mid_over_long,4) if pd.notna(snap.mid_over_long) else None,
                "mid_slope_6h": round(snap.mid_slope_6h,4) if pd.notna(snap.mid_slope_6h) else None,
                "cross_ratio": round(cr,4) if pd.notna(cr) else None,
                "score": round(score,4),
                "t7_note": "买入后至少持有 7 天方可卖出（T+7）。",
            }

            # 附带概率（不改变前端结构，前端可忽略）
            if add_prob is not None:
                details["add_prob"] = round(add_prob, 3)
                details["reduce_prob"] = round(reduce_prob, 3)

            # 控制台仅在 >=80% 时发预警
            if add_prob is not None and add_prob >= 0.80:
                print(f"⚡【加仓预警】[{p}] {knife_type} / {fp.stem} | 概率:{add_prob:.0%} | " + "；".join(add_reasons[:3]))
            if reduce_prob is not None and reduce_prob >= 0.80:
                print(f"⚠️【减仓预警】[{p}] {knife_type} / {fp.stem} | 概率:{reduce_prob:.0%} | " + "；".join(reduce_reasons[:3]))

            if ok_buy:
                details["reason"] = "动量/趋势满足、点差与跨平台一致性良好、流动性稳定。"
                buy_list.append(details)
            elif ok_watch:
                details["reason"] = "接近入场阈值（已放宽），建议观察等待进一步改善。"
                watch_list.append(details)

    # —— 对当前“持仓”给出卖出建议（特定到仓位）——
    for pos in positions:
        knife = pos["knife_type"]; item_file = pos["item_file"]; plat = pos["platform"]
        qty = int(pos["qty"]); buy_price = float(pos["buy_price"])
        buy_time = pd.to_datetime(pos["buy_time"], errors="coerce")
        if pd.isna(buy_time):  # 非法时间，跳过
            continue

        # 定位 CSV 并缓存
        item_csv = root_dir / knife / item_file
        key = (knife, item_file)
        if key not in cache_df:
            cache_df[key] = read_item_csv(item_csv, lookback_hours) if item_csv.exists() else None
        df = cache_df[key]
        if df is None or len(df) == 0:
            continue

        # 更新时间戳
        cur_ts = df["date"].max()
        if latest_ts is None or cur_ts > latest_ts: latest_ts = cur_ts

        snap = compute_platform_snapshot(df, plat, cfg)
        if snap is None or pd.isna(snap.price_sell):
            continue

        # 实时收益（按卖一价估算，含费净收益）
        sell_eff = float(snap.price_sell)
        cur_ret = net_return(sell_eff, buy_price, plat)
        if pd.isna(cur_ret): cur_ret = 0.0

        # 持有天数（按天粒度）
        holding_days = (cur_ts.normalize() - buy_time.normalize()).days

        # 更新峰值收益
        prev_peak = float(pos.get("peak_ret", 0.0))
        new_peak = max(prev_peak, cur_ret)
        pos["peak_ret"] = new_peak  # 写回内存，稍后统一保存

        # T+7 未到期：只提示状态
        if holding_days < MIN_HOLD_DAYS:
            locked_until_t7.append({
                "knife_type": knife,
                "item_name": Path(item_file).stem,
                "platform": plat,
                "qty": qty,
                "buy_price": buy_price,
                "mark_price": sell_eff,
                "cur_ret": round(cur_ret,4),
                "peak_ret": round(new_peak,4),
                "holding_days": holding_days,
                "note": f"T+7 未到期（{holding_days}/7 天）；目前仅观察，不建议卖出。"
            })
            continue

        # 到期后：判断卖出信号
        reasons = []
        if cur_ret >= cfg.tp_abs:
            reasons.append(f"达到止盈阈值({cfg.tp_abs:.1%})")
        if cur_ret <= -cfg.sl_abs:
            reasons.append(f"触发止损阈值({cfg.sl_abs:.1%})")

        # 跟踪止盈
        if new_peak >= cfg.trail_trigger:
            giveback = new_peak - cur_ret
            if giveback >= cfg.trail_giveback * new_peak:
                reasons.append(f"回撤止盈：已回吐≥{cfg.trail_giveback:.0%}峰值收益")

        # 趋势/流动性恶化
        weak_flag, weak_why = makes_sell_alert_for_snapshot(snap, cfg)
        if weak_flag:
            reasons += weak_why

        if reasons:
            sell_alerts_for_holdings.append({
                "knife_type": knife,
                "item_name": Path(item_file).stem,
                "platform": plat,
                "qty": qty,
                "buy_price": round(buy_price,2),
                "mark_price": round(sell_eff,2),
                "cur_ret": round(cur_ret,4),
                "peak_ret": round(new_peak,4),
                "holding_days": holding_days,
                "advice": "建议卖出或减仓",
                "reasons": reasons
            })
        # else：无卖出信号则不提示（减少噪音）

    # 排序裁剪
    buy_list = sorted(buy_list, key=lambda x: x["score"], reverse=True)[:min(topk, cfg.daily_topk_cap)]
    watch_list = sorted(watch_list, key=lambda x: x["score"], reverse=True)[:topk]

    # 保存持仓（更新了 peak_ret）
    save_positions(positions)

    result = {
        "asof": latest_ts.strftime("%Y-%m-%d %H:%M") if latest_ts is not None else None,
        "mode": mode_name,
        "lookback_hours": lookback_hours,
        "min_required_hours": cfg.min_hours,
        "buy_candidates": buy_list,
        "watchlist": watch_list,
        "sell_advice_for_holdings": sell_alerts_for_holdings,
        "locked_until_t7": locked_until_t7,
        "insufficient_series": insufficient,
        "skipped_files": int(skipped),
        "notes": [
            "买入后至少持有 7 天（T+7）；未到期仅观察。",
            "卖出建议基于含费净收益（卖出2%，买入0%）。",
            "若数据不足（历史小时数不够）则跳过不判断。",
            "控制台仅在加/减仓概率≥80%时输出预警。",
        ],
        "state_files": {
            "positions_json": str(POSITIONS_PATH),
            "output_json": str(RESULTS_PATH),
        }
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # 保存最新结果
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 保存历史记录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_file = HISTORY_DIR / f"reco_{timestamp}.json"
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 清理旧的历史文件（保留最近30天）
    cleanup_old_history_files()

    # 控台摘要
    print(f"=== {mode_name} ｜ 截止 {result['asof']} ===")
    print(f"买入候选:{len(buy_list)} | 观察:{len(watch_list)} | 卖出建议(持仓):{len(sell_alerts_for_holdings)} | 未到期T+7:{len(locked_until_t7)}")
    if buy_list:
        print("\n【买入候选】")
        for i,a in enumerate(buy_list,1):
            print(f"{i:>2}. [{a['platform']}] {a['knife_type']} / {a['item_name']} | 卖:{a['price_sell']} | 分:{a['score']} | 原因:{a['reason']}")
    if watch_list:
        print("\n【观察名单】")
        for i,a in enumerate(watch_list,1):
            print(f"{i:>2}. [{a['platform']}] {a['knife_type']} / {a['item_name']} | 卖:{a['price_sell']} | 分:{a['score']} | {a['reason']}")
    if sell_alerts_for_holdings:
        print("\n【卖出建议（已持仓）】")
        for i,s in enumerate(sell_alerts_for_holdings,1):
            rs = "；".join(s["reasons"])
            print(f"{i:>2}. [{s['platform']}] {s['knife_type']} / {s['item_name']} | 数:{s['qty']} | 现:{s['mark_price']} | 收益:{s['cur_ret']:+.2%} | 峰:{s['peak_ret']:+.2%} | {rs}")
    if locked_until_t7:
        print("\n【未到期（T+7）仅观察】")
        for i,s in enumerate(locked_until_t7,1):
            print(f"{i:>2}. [{s['platform']}] {s['knife_type']} / {s['item_name']} | 持有:{s['holding_days']}/7天 | 收益:{s['cur_ret']:+.2%}")

    print(f"\n已写入：{RESULTS_PATH}")
    return result

# -------------------------
# CLI
# -------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, default="dataset/匕首", help="根目录（包含各刀型子目录）")
    parser.add_argument("--mode", type=str, default="适中", choices=list(MODE_MAP.keys()), help="风格模式")
    parser.add_argument("--topk", type=int, default=8, help="每类最多返回条数")
    parser.add_argument("--lookback", type=int, default=336, help="回看小时数（默认14天）")

    # 记录买入
    parser.add_argument("--record-buy", action="store_true", help="记录一笔买入")
    parser.add_argument("--knife", type=str, help="刀型目录名（如：蝴蝶刀）")
    parser.add_argument("--item", type=str, help="物品 CSV 文件名（含 .csv）")
    parser.add_argument("--platform", type=str, choices=PLATFORMS, help="平台：BUFF 或 YYYP")
    parser.add_argument("--qty", type=int, help="数量", default=1)
    parser.add_argument("--price", type=float, help="买入单价")
    parser.add_argument("--time", type=str, help="买入时间，例如 2025-08-22 13:54")

    # 查看当前持仓
    parser.add_argument("--list-positions", action="store_true", help="列出已记录的持仓")

    args = parser.parse_args()

    root_dir = (BACKEND_DIR / args.root) if not os.path.isabs(args.root) else Path(args.root)
    if args.list_positions:
        list_positions()
        return

    if args.record_buy:
        need = [args.knife, args.item, args.platform, args.price, args.time]
        if any(v is None for v in need):
            print("❌ 记录买入缺少参数：--knife --item --platform --price --time（可选 --qty）")
            sys.exit(2)
        record_buy(args.knife, args.item, args.platform, int(args.qty), float(args.price), args.time, root_dir)
        return

    if not root_dir.exists():
        print(f"❌ 根目录不存在：{root_dir}")
        sys.exit(1)

    analyze_root(root_dir, args.mode, args.topk, args.lookback)

if __name__ == "__main__":
    main()