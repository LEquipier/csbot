# -*- coding: utf-8 -*-
"""
data_builder_butterfly_board_v2.py

目标：
- 构建「蝴蝶刀板块」的板块级短线训练数据（14天、T+7、含费三重边界标签）
- 融合：
  1) 单品多平台多指标（good_chart）
  2) 指数K线（sub/kline）→ 市场因子
  3) 实时成交量榜（vol_data_info）→ 广度/情绪
  4) 单品成交量历史 & 磨损（vol_data_detail）→ 量能兜底 + 品质因子

输出：
- ./dataset/butterfly_board_panel.parquet
- ./dataset/butterfly_board_panel.csv

依赖：
  pip install pandas numpy pyarrow fastparquet tqdm python-dateutil
"""
import os, json, argparse, time
from typing import List, Dict, Any, Tuple, Union
import numpy as np
import pandas as pd
from tqdm import tqdm

# 你的客户端（放在项目内），需提供：index_kline / get_good_id / good_detail / batch_price / good_chart /
#                                  vol_data_info / vol_data_detail
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from CSQAQ import CsqaqClient
from config import API_TOKEN

# ==================== 可调参数 ====================
PLATFORM_MAP = {1: "BUFF", 2: "YYYP", 3: "Steam"}
DEFAULT_PLATFORMS = [1, 2, 3]  # BUFF + YYYP + Steam

# 平台费率（可按需覆盖；Steam ~15%，BUFF 卖家 ~2.5%）
PLATFORM_FEES_SELL = {1: 0.025, 2: 0.03, 3: 0.15}  # 卖出费率，净得 = price*(1-fee) - withdraw
PLATFORM_FEES_BUY  = {1: 0.00,  2: 0.00, 3: 0.00}  # 买入费率（多数场景可忽略）
WITHDRAW_FEES      = {1: 0.00,  2: 0.00, 3: 0.00}

MIN_HOLD_DAYS   = 7     # T+7
LABEL_HORIZON   = 14    # 14天短线
TAKE_PROFIT_PCT = 0.08  # 止盈 +8%（含费）
STOP_LOSS_PCT   = -0.05 # 止损 -5%（含费）

# 机器学习常用指标（good_chart keys）
CHART_KEYS = [
    "sell_price", "buy_price",
    "sell_num", "buy_num",
]
PERIOD = "1095"   # 3年
STYLE  = "all_style"

# 板块筛选条件
MIN_PRICE_THRESHOLD = 4000
BUTTERFLY_KEYWORDS = ["蝴蝶刀", "Butterfly", "butterfly"]

# ==================== 小工具 ====================
def ensure_dir(p: str): os.makedirs(p, exist_ok=True)

def safe_get(d: Dict, *ks, default=None):
    cur = d
    for k in ks:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

# ==================== 价格含费 ====================
def net_sell_proceed(price: Union[float, np.ndarray], platform: int) -> Union[float, np.ndarray]:
    fee = PLATFORM_FEES_SELL.get(platform, 0.0)
    wd  = WITHDRAW_FEES.get(platform, 0.0)
    return price * (1 - fee) - wd

def net_buy_cost(price: Union[float, np.ndarray], platform: int) -> Union[float, np.ndarray]:
    fee = PLATFORM_FEES_BUY.get(platform, 0.0)
    return price * (1 + fee)

# ==================== 数据拉取：指数 / 榜单 / 单品成交量 ====================
def fetch_index_kline(client: CsqaqClient, index_id: int = 1, k_type: str = "1day") -> pd.DataFrame:
    """
    /api/v1/sub/kline?id=1&type=1day
    返回：date, idx_o, idx_h, idx_l, idx_c, idx_v, idx_ret_1d, idx_vol_14d, idx_dd_60d, idx_risk_on
    """
    j = client.index_kline(index_id=index_id, period=k_type)
    arr = safe_get(j, "data", default=[])
    if not arr: return pd.DataFrame()

    df = pd.DataFrame(arr)
    # t（字符串毫秒）→ date
    df["date"] = pd.to_datetime(df["t"].astype(str), unit="ms", utc=True)\
                    .dt.tz_convert("America/New_York").dt.normalize()
    df = df.rename(columns={"o":"idx_o","h":"idx_h","l":"idx_l","c":"idx_c","v":"idx_v"})
    cols = ["date","idx_o","idx_h","idx_l","idx_c","idx_v"]
    df = df[cols].sort_values("date").reset_index(drop=True)

    df["idx_c"] = pd.to_numeric(df["idx_c"], errors="coerce")
    df["idx_ret_1d"]  = df["idx_c"].pct_change(1)
    df["idx_vol_14d"] = df["idx_ret_1d"].rolling(14).std()
    df["idx_max_60d"] = df["idx_c"].rolling(60).max()
    df["idx_dd_60d"]  = (df["idx_c"] / df["idx_max_60d"] - 1.0)
    df["idx_risk_on"] = ((df["idx_ret_1d"].rolling(5).mean() > 0) &
                         (df["idx_vol_14d"] < df["idx_vol_14d"].median())).astype("Int8")
    return df

def fetch_vol_leaderboard(client: CsqaqClient) -> Tuple[pd.DataFrame, Dict[str,int]]:
    """
    /api/v1/info/vol_data_info (POST)
    返回：
      - df：date, good_id, vol_statistic, vol_sum_price, vol_avg_price
      - gid->vol_id 映射（从原始返回的 'id' 字段提取）
    """
    raw = client.vol_data_info()
    arr = safe_get(raw, "data", default=[])
    if not arr: return pd.DataFrame(), {}

    df = pd.DataFrame(arr)
    df = df.rename(columns={
        "good_id": "good_id",
        "statistic": "vol_statistic",
        "sum_price": "vol_sum_price",
        "avg_price": "vol_avg_price",
        "updated_at": "updated_at"
    })
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True, errors="coerce")\
                           .dt.tz_convert("America/New_York")
    df["date"] = df["updated_at"].dt.normalize()
    agg = (df.groupby(["date","good_id"])
             .agg(vol_statistic=("vol_statistic","last"),
                  vol_sum_price=("vol_sum_price","last"),
                  vol_avg_price=("vol_avg_price","last"))
             .reset_index())
    gid2volid = {}
    for it in arr:
        gid, vid = it.get("good_id"), it.get("id")
        if gid is not None and vid is not None:
            gid2volid[str(gid)] = int(vid)
    return agg, gid2volid

def fetch_item_volume_series(client: CsqaqClient, vol_id: int, is_weapon: bool = True,
                             start_day: str = "2023-01-01") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    /api/v1/info/vol_data_detail (POST)
    返回 (chart_df, wear_df)
      chart_df: date, vol_statistic, vol_avg_price, vol_sum_price
      wear_df : created_at(到秒), price, abrade
    """
    j = client.vol_data_detail(vol_id=vol_id, is_weapon=is_weapon, start_day=start_day)
    ch = safe_get(j, "data", "chart", default=[])
    ls = safe_get(j, "data", "list",  default=[])

    chart_df = pd.DataFrame(ch)
    if not chart_df.empty:
        chart_df["date"] = pd.to_datetime(chart_df["updated_at"], utc=True, errors="coerce")\
                              .dt.tz_convert("America/New_York").dt.normalize()
        chart_df = chart_df.rename(columns={
            "statistic":"vol_statistic",
            "avg_price":"vol_avg_price",
            "sum_price":"vol_sum_price"
        })
        chart_df = chart_df[["date","vol_statistic","vol_avg_price","vol_sum_price"]]

    wear_df = pd.DataFrame(ls)
    if not wear_df.empty:
        wear_df["created_at"] = pd.to_datetime(wear_df["created_at"], utc=True, errors="coerce")\
                                   .dt.tz_convert("America/New_York")
        wear_df["abrade"] = pd.to_numeric(wear_df["abrade"], errors="coerce")
        wear_df = wear_df[["created_at","price","abrade"]]

    return chart_df, wear_df

# ==================== 单品时间序列（good_chart） ====================
def fetch_item_panel(
    client: CsqaqClient,
    good_id: Union[int,str],
    platforms: List[int] = DEFAULT_PLATFORMS,
    chart_keys: List[str] = CHART_KEYS,
    period: str = "1095",
    style: str = "all_style",
    max_retries: int = 6,
    retry_delay: int = 6,
) -> pd.DataFrame:
    """
    用 /info/chart 获取单品多平台多指标的日序列
    列：good_id, date, {PLATFORM_key...}
    """
    frames = []
    for key in chart_keys:
        for p in platforms:
            ok, ntry, delay = False, 0, retry_delay
            while not ok and ntry < max_retries:
                try:
                    j = client.good_chart(good_id, key=key, platform=p, period=period, style=style)
                    data = safe_get(j, "data", default={})
                    if not data: 
                        break

                    timestamp = data.get("timestamp", [])
                    main_data = data.get("main_data", [])
                    num_data = data.get("num_data", [])

                    if not timestamp: 
                        break

                    df_data = {"timestamp": timestamp}

                    # 对齐 main_data
                    if main_data:
                        m = min(len(timestamp), len(main_data))
                        df_data["timestamp"] = timestamp[:m]
                        df_data["main_data"] = main_data[:m]
                    # 对齐 num_data
                    if num_data:
                        if "main_data" in df_data:
                            m = len(df_data["timestamp"])
                            df_data["num_data"] = num_data[:m]
                        else:
                            m = min(len(timestamp), len(num_data))
                            df_data["timestamp"] = timestamp[:m]
                            df_data["num_data"] = num_data[:m]

                    df = pd.DataFrame(df_data)
                    # 时间 → 日
                    df["date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)\
                                    .dt.tz_convert("America/New_York").dt.normalize()

                    col_base = f"{PLATFORM_MAP.get(p,f'P{p}')}_{key}"
                    if "main_data" in df.columns:
                        val = pd.to_numeric(df["main_data"], errors="coerce")
                    elif "num_data" in df.columns:
                        val = pd.to_numeric(df["num_data"], errors="coerce")
                    elif "c" in df.columns:
                        val = pd.to_numeric(df["c"], errors="coerce")
                    elif "v" in df.columns:
                        val = pd.to_numeric(df["v"], errors="coerce")
                    else:
                        guess = [c for c in df.columns if c not in ("t","timestamp","date")]
                        val = pd.to_numeric(df[guess[0]], errors="coerce") if guess else pd.Series(dtype=float)

                    if val.isna().all():
                        break

                    df[col_base] = val
                    df["good_id"] = str(good_id)
                    frames.append(df[["good_id","date",col_base]])
                    ok = True
                except Exception:
                    ntry += 1
                    if ntry < max_retries:
                        time.sleep(delay)
                        delay = min(int(delay * 1.5), 30)
                    else:
                        break

    if not frames: 
        print(f"⚠️ 商品 {good_id} 没有获取到任何数据框架")
        return pd.DataFrame()

    print(f"📊 商品 {good_id} 获取到 {len(frames)} 个数据框架")
    print(f"📋 第一个框架列: {list(frames[0].columns)}")
    
    # 合并 + 规范为日频 + 前向填充（不产生需要 droplevel 的多级索引）
    out = frames[0]
    for i, f in enumerate(frames[1:], 1):
        print(f"🔗 合并第 {i+1} 个框架，列: {list(f.columns)}")
        out = out.merge(f, on=["good_id","date"], how="outer")
    out["date"] = pd.to_datetime(out["date"])
    out = (
        out.groupby(["good_id", pd.Grouper(key="date", freq="1D")]).last()
           .reset_index()
           .sort_values(["good_id","date"])
    )
    out = out.groupby("good_id", group_keys=False).ffill()
    
    # 确保good_id列存在
    if "good_id" not in out.columns:
        print(f"⚠️ 警告：处理后的数据缺少good_id列，列名：{list(out.columns)}")
        # 重新添加good_id列
        out["good_id"] = str(good_id)
    
    print(f"✅ 商品 {good_id} 处理完成: shape={out.shape}, 列={list(out.columns)}")
    return out

# ==================== 板块：特征工程 ====================
def add_price_tech_features(df: pd.DataFrame, price_col: str, prefix: str) -> pd.DataFrame:
    x = pd.to_numeric(df[price_col], errors="coerce")
    df[f"{prefix}_ret_1d"]  = x.pct_change(1)
    df[f"{prefix}_ret_3d"]  = x.pct_change(3)
    df[f"{prefix}_ret_7d"]  = x.pct_change(7)
    df[f"{prefix}_ret_14d"] = x.pct_change(14)

    df[f"{prefix}_vol_7d"]  = df[f"{prefix}_ret_1d"].rolling(7).std()
    df[f"{prefix}_vol_14d"] = df[f"{prefix}_ret_1d"].rolling(14).std()

    ma5  = x.rolling(5).mean()
    ma20 = x.rolling(20).mean()
    df[f"{prefix}_ma_5"]   = ma5
    df[f"{prefix}_ma_20"]  = ma20
    df[f"{prefix}_pos_ma5"]  = x / ma5
    df[f"{prefix}_pos_ma20"] = x / ma20

    # 布林
    ma = x.rolling(20).mean()
    sd = x.rolling(20).std()
    up, dn = ma + 2*sd, ma - 2*sd
    df[f"{prefix}_boll_up"] = up
    df[f"{prefix}_boll_dn"] = dn
    width = (up - dn) / ma.replace(0, np.nan)
    df[f"{prefix}_boll_width"] = width

    # RSI14
    delta = x.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df[f"{prefix}_rsi14"] = 100 - (100 / (1 + rs))
    return df

def add_cross_platform_features(df: pd.DataFrame) -> pd.DataFrame:
    # 价差/比值
    if {"BUFF_sell_price","Steam_sell_price"} <= set(df.columns):
        df["buff_steam_diff"]  = df["Steam_sell_price"] - df["BUFF_sell_price"]
        df["buff_steam_ratio"] = df["Steam_sell_price"] / df["BUFF_sell_price"]
    if {"BUFF_sell_price","YYYP_sell_price"} <= set(df.columns):
        df["buff_yyyp_diff"]  = df["YYYP_sell_price"] - df["BUFF_sell_price"]
        df["buff_yyyp_ratio"] = df["YYYP_sell_price"] / df["BUFF_sell_price"]
    # 流动性
    if {"BUFF_sell_num","BUFF_buy_num"} <= set(df.columns):
        df["buff_liq_ratio"]  = df["BUFF_buy_num"] / (df["BUFF_sell_num"] + 1)
        df["buff_orders"]     = df["BUFF_buy_num"] + df["BUFF_sell_num"]
    return df

def gen_triple_barrier_labels(
    df: pd.DataFrame,
    trade_platform: int,
    price_col: str,
    take_profit: float = 0.08,
    stop_loss: float = -0.05,
    horizon_days: int = 14,
    min_hold_days: int = 7,
    out_col: str = None
) -> pd.DataFrame:
    """
    三重边界（含费）：
      entry_cost = net_buy_cost(price_t0)
      window t ∈ [t0+min_hold, t0+horizon]
      if max_t net_sell_proceed(price_t) / entry_cost - 1 >= TP → +1
      elif min_t net_sell_proceed(price_t) / entry_cost - 1 <= SL → -1
      else 0
    """
    df = df.copy()
    x = pd.to_numeric(df[price_col], errors="coerce").values
    n = len(df)
    label = np.zeros(n, dtype=int)
    for i in range(n):
        p0 = x[i]
        if not np.isfinite(p0): continue
        entry = net_buy_cost(p0, trade_platform)
        start, end = i + min_hold_days, min(i + horizon_days, n - 1)
        if start > end: continue
        window = x[start:end+1]
        rets = (net_sell_proceed(window, trade_platform) - entry) / entry
        tp = np.where(rets >= take_profit)[0]
        sl = np.where(rets <= stop_loss)[0]
        if tp.size > 0: label[i] = 1
        elif sl.size > 0: label[i] = -1
        else: label[i] = 0
    if not out_col:
        out_col = f"label_14d_tp{int(take_profit*100)}_sl{int(abs(stop_loss)*100)}"
    df[out_col] = label
    return df

# ==================== 板块构建流程 ====================
def fetch_butterfly_universe(client: CsqaqClient,
                             max_pages: int = 6,
                             page_size: int = 50,
                             max_items: int = None) -> List[str]:
    """
    使用 get_good_id('蝴蝶刀') 搜索全量，再用 good_detail/batch_price 过滤价格≥阈值
    返回 good_id 列表（字符串）
    """
    results = []
    seen = set()
    for page in range(1, max_pages+1):
        try:
            resp = client.get_good_id("蝴蝶刀", page_index=page, page_size=page_size)
            data = safe_get(resp, "data", "data", default={})
            if not data: break
            for gid_str, rec in data.items():
                name = rec.get("name", rec.get("market_hash_name","")).lower()
                if any(kw.lower() in name for kw in BUTTERFLY_KEYWORDS):
                    if gid_str not in seen:
                        seen.add(gid_str)
                        results.append(gid_str)
        except Exception:
            continue

    # 价格过滤（尽量使用 good_detail + batch_price 兜底）
    filtered = []
    for gid in results:
        if max_items and len(filtered) >= max_items:
            break
        try:
            det = client.good_detail(gid)
            info = safe_get(det, "data", default={})
            # 尝试多个价格字段
            candidates = []
            for k in ["buff_sell_price","yyyp_sell_price","steam_sell_price",
                      "buffBuyPrice","yyypBuyPrice","steamBuyPrice",
                      "buffSellPrice","yyypSellPrice","steamSellPrice",
                      "buff_buy_price","yyyp_buy_price","steam_buy_price"]:
                v = info.get(k)
                if v is not None:
                    try: v = float(v)
                    except: v = np.nan
                    if np.isfinite(v) and v > 0: candidates.append(v)
            if not candidates:
                # batch_price 再试
                mhn = safe_get(info, "goods_info","market_hash_name", default=None)
                if mhn:
                    bp = client.batch_price([mhn])
                    succ = safe_get(bp, "data","success", default={})
                    ditem = succ.get(mhn, {})
                    for k in ["buffSellPrice","yyypSellPrice","steamSellPrice",
                              "buffBuyPrice","yyypBuyPrice","steamBuyPrice"]:
                        v = ditem.get(k)
                        if v is not None:
                            try: v = float(v)
                            except: v = np.nan
                            if np.isfinite(v) and v>0: candidates.append(v)
            max_price = max(candidates) if candidates else 0
            if max_price >= MIN_PRICE_THRESHOLD:
                filtered.append(gid)
        except Exception:
            continue
    return filtered

def build_butterfly_board_dataset(
    token: str,
    out_dir: str = "./dataset",
    platforms: List[int] = DEFAULT_PLATFORMS,
    chart_keys: List[str] = CHART_KEYS,
    period: str = "1095",
    style: str = "all_style",
    test_mode: bool = False
) -> pd.DataFrame:
    """
    步骤：
      A) 选宇宙（蝴蝶刀符合价位的 good_id）
      B) 拉单品时间序列并横向合并为「板块面板」（逐日：每个 good_id 一行）
      C) 计算「板块横截面统计」与「市场/广度/量能兜底」并合并
      D) 生成含费三重边界标签（以 BUFF 卖价为参考）
    """
    ensure_dir(out_dir)
    client = CsqaqClient(api_token=token)

    # ------- A) 板块宇宙 -------
    print("🔍 构建蝴蝶刀宇宙 ...")
    good_ids = fetch_butterfly_universe(
        client, 
        max_pages=2 if test_mode else 8, 
        page_size=20 if test_mode else 50,
        max_items=5 if test_mode else None  # 测试模式获取5个，生产模式获取所有
    )
    if not good_ids: raise RuntimeError("未找到蝴蝶刀宇宙（请检查关键词或阈值）")
    print(f"✅ 蝴蝶刀候选数：{len(good_ids)}")

    # ------- B) 拉单品面板 -------
    print("📡 拉取单品时间序列（good_chart） ...")
    item_frames = []
    for gid in tqdm(good_ids):
        df = fetch_item_panel(client, gid, platforms=platforms, chart_keys=chart_keys, period=period, style=style)
        if df.empty: 
            continue
        # 为每个常用价格列添加技术特征
        for p in platforms:
            col = f"{PLATFORM_MAP.get(p,f'P{p}')}_sell_price"
            if col in df.columns:
                df = add_price_tech_features(df, col, prefix=col)
        df = add_cross_platform_features(df)
        item_frames.append(df)

    if not item_frames:
        raise RuntimeError("未获取到任何单品时间序列。")

    print(f"🔗 准备合并 {len(item_frames)} 个商品的数据框架")
    for i, df in enumerate(item_frames):
        print(f"📊 商品 {i+1} 框架: shape={df.shape}, 列={list(df.columns)}")
    
    panel = pd.concat(item_frames, ignore_index=True)
    print(f"📋 合并后面板: shape={panel.shape}, 列={list(panel.columns)}")
    
    # 确保good_id列存在
    if "good_id" not in panel.columns:
        raise RuntimeError("合并后的数据缺少good_id列")
    panel["good_id"] = panel["good_id"].astype(str)
    panel = panel.sort_values(["good_id","date"]).drop_duplicates(["good_id","date"])

    # ------- C1) 指数K线（市场因子） -------
    print("📈 合并指数K线（市场因子） ...")
    idx_df = fetch_index_kline(client, index_id=1, k_type="1day")
    if not idx_df.empty:
        panel = panel.merge(idx_df, on="date", how="left")

    # ------- C2) 实时成交量榜（广度/情绪） -------
    print("📊 合并当日榜单（广度/情绪） ...")
    lb_df, gid2volid = fetch_vol_leaderboard(client)
    if not lb_df.empty:
        lb_df["good_id"] = lb_df["good_id"].astype(str)
        panel = panel.merge(lb_df, on=["date","good_id"], how="left")
        # 广度：当日上涨占比（按 BUFF_sell_price_ret_1d）
        ret_col = "BUFF_sell_price_ret_1d" if "BUFF_sell_price_ret_1d" in panel.columns else None
        if ret_col:
            breadth = (panel[["date","good_id",ret_col]].dropna()
                       .assign(up=lambda d: (d[ret_col] > 0).astype(int))
                       .groupby("date")["up"].mean().to_frame("breadth_up_all").reset_index())
            panel = panel.merge(breadth, on="date", how="left")

    # ------- C3) 单品成交量历史兜底（仅缺失时） -------
    print("🧩 对缺失量能进行兜底（vol_data_detail） ...")
    # 如果你后续把 daily_volume 拉到了面板里，可在这里按需兜底；当前用 vol_statistic 作为总量参考
    if "vol_statistic" not in panel.columns and gid2volid:
        # 可选：对少量代表性ID做兜底，避免过多请求
        to_fix = list(gid2volid.keys())[:30]
        for gid in tqdm(to_fix):
            vid = gid2volid.get(gid)
            if not vid: continue
            chart_df, _ = fetch_item_volume_series(client, vol_id=vid, is_weapon=True, start_day="2023-01-01")
            if chart_df.empty: continue
            chart_df["good_id"] = str(gid)
            panel = panel.merge(chart_df, on=["good_id","date"], how="left", suffixes=("","_from_volapi"))
            if "total_daily_volume" not in panel.columns:
                panel["total_daily_volume"] = panel["vol_statistic"]
            else:
                panel["total_daily_volume"] = panel["total_daily_volume"].fillna(panel["vol_statistic"])

    # ------- C4) 板块横截面统计（按日聚合） -------
    print("🧮 计算板块横截面统计 ...")
    ref_price = "BUFF_sell_price" if "BUFF_sell_price" in panel.columns else None
    if ref_price:
        grp = panel[["date","good_id",ref_price]].dropna()
        agg = (grp.groupby("date")[ref_price]
               .agg(board_median="median", board_mean="mean", board_std="std", board_min="min", board_max="max")
               .reset_index())
        panel = panel.merge(agg, on="date", how="left")
        panel["board_zscore"] = (panel[ref_price] - panel["board_mean"]) / panel["board_std"]

    # ------- D) 生成含费三重边界标签（以 BUFF 为例） -------
    print("🏷️ 生成含费三重边界标签 ...")
    if ref_price and panel[ref_price].notna().any():
        panel = (panel.sort_values(["good_id","date"])
                       .groupby("good_id", group_keys=False)
                       .apply(lambda d: gen_triple_barrier_labels(
                           d, trade_platform=1, price_col=ref_price,
                           take_profit=0.08, stop_loss=-0.05,
                           horizon_days=14, min_hold_days=7)))
    else:
        print("⚠️ 缺少参考价格列，跳过标签。")

    # 清理与保存
    panel = panel.sort_values(["good_id","date"]).reset_index(drop=True)
    print("\n🔎 数据质量：")
    print(f"  总行数: {len(panel)}")
    print(f"  商品数: {panel['good_id'].nunique()}")
    print(f"  时间范围: {panel['date'].min()} → {panel['date'].max()}")
    print(f"  列数: {panel.shape[1]}")

    ensure_dir(out_dir)
    out_csv = os.path.join(out_dir, "butterfly_board_panel.csv")
    out_pq  = os.path.join(out_dir, "butterfly_board_panel.parquet")
    panel.to_csv(out_csv, index=False)
    try:
        panel.to_parquet(out_pq, index=False)
    except Exception as e:
        print(f"⚠️ 保存 Parquet 失败：{e}")

    print(f"✅ 保存：{out_csv}")
    print(f"✅ 保存：{out_pq}（如失败已忽略）")
    return panel

# ==================== CLI ====================
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=API_TOKEN, help="CSQAQ API Token")
    ap.add_argument("--out", default="./dataset", help="输出目录")
    ap.add_argument("--platforms", default="1,2,3", help="平台（1=BUFF,2=YYYP,3=Steam）")
    ap.add_argument("--period", default="1095", help="历史周期（如 365/1095）")
    ap.add_argument("--style", default="all_style", help="图表样式（默认 all_style）")
    ap.add_argument("--take_profit", type=float, default=0.08, help="止盈比例（含费），如 0.08")
    ap.add_argument("--stop_loss", type=float, default=-0.05, help="止损比例（含费），如 -0.05")
    ap.add_argument("--min_hold", type=int, default=7, help="最短持有天数（T+7 → 7）")
    ap.add_argument("--horizon", type=int, default=14, help="标签窗口天数（14）")
    ap.add_argument("--test", action="store_true", help="测试模式（小样本）")
    args = ap.parse_args()

    if not args.token:
        raise SystemExit("需要 --token 或设置环境变量 CSQAQ_TOKEN")

    # 使用命令行参数
    period = args.period
    style = args.style
    take_profit = args.take_profit
    stop_loss = args.stop_loss
    min_hold = args.min_hold
    horizon = args.horizon

    pf = [int(x.strip()) for x in args.platforms.split(",") if x.strip()]

    df = build_butterfly_board_dataset(
        token=args.token,
        out_dir=args.out,
        platforms=pf,
        chart_keys=CHART_KEYS,
        period=args.period,
        style=args.style,
        test_mode=args.test
    )
    print(f"完成。rows={len(df)}, goods={df['good_id'].nunique()}")