#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CSBOT iOS应用API接口（增强版）
- 保留原有全部接口
- 新增：
  1) GET /api/items            —— 列出所有监控物品（大类/刀型/CSV）
  2) GET /api/item/series      —— 返回某个CSV的K线+MA数据
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, asdict
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import numpy as np

# 添加项目路径
sys.path.append(os.path.dirname(__file__))
from Model.model import analyze_root, load_positions, save_positions, record_buy, MODE_MAP
from Model.build_database import DatabaseBuilder
from auto_run import AutoDatabaseUpdater

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 全局配置
BACKEND_DIR = Path(__file__).resolve().parent
MODEL_DIR = BACKEND_DIR / "Model"
RESULTS_DIR = MODEL_DIR / "results"
STATE_DIR = MODEL_DIR / "state"
DATASET_DIR = MODEL_DIR / "dataset"

# 确保目录存在
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

# ==================== 数据模型 ====================

@dataclass
class AnalysisConfig:
    """分析配置"""
    mode: str = "适中"
    topk: int = 8
    lookback_hours: int = 336
    root_dir: str = "dataset/匕首"

@dataclass
class SystemStatus:
    """系统状态"""
    database_last_update: Optional[str] = None
    analysis_last_run: Optional[str] = None
    total_items: int = 0
    active_positions: int = 0
    system_health: str = "healthy"
    memory_usage: float = 0.0
    disk_usage: float = 0.0

@dataclass
class PerformanceMetrics:
    """性能指标"""
    total_return: float = 0.0
    win_rate: float = 0.0
    avg_holding_days: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    total_trades: int = 0

# ==================== 工具函数（原有） ====================

def get_system_status() -> SystemStatus:
    """获取系统状态"""
    status = SystemStatus()

    # 检查数据库更新时间
    db_files = list(DATASET_DIR.rglob("*.csv"))
    if db_files:
        latest_file = max(db_files, key=lambda f: f.stat().st_mtime)
        status.database_last_update = datetime.fromtimestamp(
            latest_file.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M:%S")
        status.total_items = len(db_files)

    # 检查分析结果更新时间
    reco_file = RESULTS_DIR / "realtime_reco.json"
    if reco_file.exists():
        status.analysis_last_run = datetime.fromtimestamp(
            reco_file.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M:%S")

    # 检查持仓数量
    positions = load_positions()
    status.active_positions = len(positions)

    # 检查系统健康状态
    try:
        if status.total_items == 0:
            status.system_health = "no_data"
        elif status.analysis_last_run is None:
            status.system_health = "no_analysis"
        else:
            status.system_health = "healthy"
    except Exception as e:
        status.system_health = f"error: {str(e)}"

    return status


def calculate_performance_metrics() -> PerformanceMetrics:
    """计算性能指标"""
    metrics = PerformanceMetrics()

    try:
        # 读取历史记录
        history_files = list((RESULTS_DIR / "history").glob("reco_*.json"))
        if not history_files:
            return metrics

        # 分析历史数据
        all_trades = []
        for file in history_files[-30:]:  # 最近30个记录
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'sell_advice_for_holdings' in data:
                    all_trades.extend(data['sell_advice_for_holdings'])

        if all_trades:
            returns = [trade.get('cur_ret', 0) for trade in all_trades]
            metrics.total_return = float(np.sum(returns))
            metrics.win_rate = float(len([r for r in returns if r > 0]) / len(returns))
            metrics.total_trades = int(len(all_trades))

            # 计算夏普比率（简化版）
            if len(returns) > 1:
                avg_return = float(np.mean(returns))
                std_return = float(np.std(returns))
                if std_return > 0:
                    metrics.sharpe_ratio = avg_return / std_return

            # 计算最大回撤
            cumulative = np.cumsum(returns)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = cumulative - running_max
            metrics.max_drawdown = float(abs(np.min(drawdown)) if len(drawdown) > 0 else 0)

        # 计算平均持仓天数
        positions = load_positions()
        if positions:
            holding_days = []
            for pos in positions:
                buy_time = datetime.strptime(pos['buy_time'], "%Y-%m-%d %H:%M")
                days = (datetime.now() - buy_time).days
                holding_days.append(days)
            metrics.avg_holding_days = float(np.mean(holding_days) if holding_days else 0)

    except Exception as e:
        logger.error(f"计算性能指标时出错: {e}")

    return metrics


def get_market_overview() -> Dict[str, Any]:
    """获取市场概览"""
    try:
        # 读取最新分析结果
        reco_file = RESULTS_DIR / "realtime_reco.json"
        if not reco_file.exists():
            return {"error": "No analysis data available"}

        with open(reco_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 统计各平台数据
        platform_stats = {"BUFF": 0, "YYYP": 0}
        category_stats = {}

        for item in data.get('buy_candidates', []):
            platform = item.get('platform', 'Unknown')
            category = item.get('knife_type', 'Unknown')

            platform_stats[platform] = platform_stats.get(platform, 0) + 1
            category_stats[category] = category_stats.get(category, 0) + 1

        return {
            "total_candidates": len(data.get('buy_candidates', [])),
            "total_watchlist": len(data.get('watchlist', [])),
            "platform_distribution": platform_stats,
            "category_distribution": category_stats,
            "last_analysis": data.get('asof'),
            "analysis_mode": data.get('mode'),
            "insufficient_data_count": len(data.get('insufficient_series', []))
        }

    except Exception as e:
        logger.error(f"获取市场概览时出错: {e}")
        return {"error": str(e)}

# ==================== 新增：K线/MA 所需工具函数 ====================

VALID_ROOTS = ["匕首", "步枪", "手枪", "手套", "探员"]

def _safe_join_dataset(*parts: str) -> Path:
    """将相对路径拼到 DATASET_DIR，并确保不越界"""
    p = DATASET_DIR.joinpath(*parts).resolve()
    if not str(p).startswith(str(DATASET_DIR.resolve())):
        raise ValueError("Invalid path outside dataset")
    return p

def _scan_items() -> Dict[str, Any]:
    """
    扫描 dataset，返回：{ category: { type: [ {file, relative_path, size, mtime}...] } }
    其中 relative_path 形如：匕首/弯刀/6927_弯刀 _ 屠夫 崭新出厂.csv
    """
    result: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    if not DATASET_DIR.exists():
        return result

    for category_dir in DATASET_DIR.iterdir():
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        result.setdefault(category, {})

        for type_dir in category_dir.iterdir():
            if not type_dir.is_dir():
                continue
            type_name = type_dir.name
            files: List[Dict[str, Any]] = []
            for csvf in type_dir.glob("*.csv"):
                rel = csvf.relative_to(DATASET_DIR).as_posix()
                stat = csvf.stat()
                files.append({
                    "file": csvf.name,
                    "relative_path": rel,
                    "size_bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            # 仅在有文件时返回该 type
            if files:
                result[category][type_name] = sorted(files, key=lambda x: x["file"])
    return result

def _load_item_csv(path_in_dataset: str) -> pd.DataFrame:
    """
    读取单个 CSV（相对 dataset 的路径）
    兼容时间列名 'data' 或 'date'，并解析为 DatetimeIndex
    """
    csv_path = _safe_join_dataset(path_in_dataset)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {path_in_dataset}")

    # 常见编码优先 utf-8
    df = pd.read_csv(csv_path, encoding="utf-8")
    cols = {c.strip(): c for c in df.columns}  # 去空格映射到原列名
    time_key = None
    for cand in ("date", "data", "时间"):
        if cand in cols:
            time_key = cols[cand]
            break
    if time_key is None:
        # 也适配首列为时间的情况
        time_key = df.columns[0]

    df[time_key] = pd.to_datetime(df[time_key], errors="coerce")
    df = df.dropna(subset=[time_key]).sort_values(time_key)
    df = df.set_index(time_key)

    # 统一列名别名
    def has(col): return col in cols
    def col(name): return cols.get(name, name)

    # 价格列名（四选一）
    price_map = {
        ("BUFF", "sell"): col("BUFF_sell_price") if has("BUFF_sell_price") else None,
        ("BUFF", "buy"):  col("BUFF_buy_price")  if has("BUFF_buy_price")  else None,
        ("YYYP", "sell"): col("YYYP_sell_price") if has("YYYP_sell_price") else None,
        ("YYYP", "buy"):  col("YYYP_buy_price")  if has("YYYP_buy_price")  else None,
    }

    return df, price_map

def _build_series_and_ohlc(
    df: pd.DataFrame,
    price_col: str,
    freq: str = "H",
    ma_windows: List[int] = [24, 72, 168]
) -> Dict[str, Any]:
    """
    根据 price_col 构建：
    - 原始 price 序列（时间/价格）
    - 频率聚合后的 OHLC（K线）
    - 对原始序列计算 MA 均线
    """
    price = df[price_col].astype(float).dropna()
    if price.empty:
        return {"price": [], "ohlc": [], "ma": {}}

    # 原始序列（下发给前端画细粒度折线）
    price_series = [
        {"t": ts.isoformat(), "p": float(v)}
        for ts, v in price.items()
    ]

    # 频率聚合 K 线（open/high/low/close）
    ohlc = price.resample(freq).agg(["first", "max", "min", "last"]).dropna(how="any")
    ohlc_records = [
        {
            "t": idx.isoformat(),
            "o": float(row["first"]),
            "h": float(row["max"]),
            "l": float(row["min"]),
            "c": float(row["last"]),
        }
        for idx, row in ohlc.iterrows()
    ]

    # 移动平均（在原始频率上计算）
    ma_dict: Dict[str, List[Dict[str, Any]]] = {}
    for w in ma_windows:
        ser = price.rolling(window=w, min_periods=max(1, int(w*0.6))).mean()
        ma_dict[str(w)] = [{"t": ts.isoformat(), "ma": float(v)} for ts, v in ser.dropna().items()]

    return {"price": price_series, "ohlc": ohlc_records, "ma": ma_dict}

def _parse_time_range(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    if start:
        try:
            start_dt = pd.to_datetime(start)
            df = df[df.index >= start_dt]
        except Exception:
            pass
    if end:
        try:
            end_dt = pd.to_datetime(end)
            df = df[df.index <= end_dt]
        except Exception:
            pass
    return df

# ==================== API路由（原有 + 新增） ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.1.0"
    })

@app.route('/api/status', methods=['GET'])
def get_status():
    """获取系统状态"""
    status = get_system_status()
    return jsonify(asdict(status))

@app.route('/api/performance', methods=['GET'])
def get_performance():
    """获取性能指标"""
    metrics = calculate_performance_metrics()
    return jsonify(asdict(metrics))

@app.route('/api/market/overview', methods=['GET'])
def get_market_overview_api():
    """获取市场概览"""
    return jsonify(get_market_overview())

@app.route('/api/analysis/current', methods=['GET'])
def get_current_analysis():
    """获取当前分析结果"""
    try:
        reco_file = RESULTS_DIR / "realtime_reco.json"
        if not reco_file.exists():
            return jsonify({"error": "No analysis data available"}), 404

        with open(reco_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return jsonify(data)

    except Exception as e:
        logger.error(f"获取当前分析结果时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/analysis/run', methods=['POST'])
def run_analysis():
    """运行分析"""
    try:
        data = request.get_json() or {}
        config = AnalysisConfig(
            mode=data.get('mode', '适中'),
            topk=data.get('topk', 8),
            lookback_hours=data.get('lookback_hours', 336),
            root_dir=data.get('root_dir', 'dataset/匕首')
        )

        # 验证模式
        if config.mode not in MODE_MAP:
            return jsonify({"error": f"Invalid mode: {config.mode}"}), 400

        # 运行分析
        root_path = MODEL_DIR / config.root_dir
        if not root_path.exists():
            return jsonify({"error": f"Root directory not found: {config.root_dir}"}), 404

        result = analyze_root(root_path, config.mode, config.topk, config.lookback_hours)

        return jsonify({
            "success": True,
            "message": "Analysis completed successfully",
            "result": result
        })

    except Exception as e:
        logger.error(f"运行分析时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/positions', methods=['GET'])
def get_positions():
    """获取持仓信息"""
    try:
        positions = load_positions()
        return jsonify({
            "positions": positions,
            "count": len(positions),
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"获取持仓信息时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/positions/add', methods=['POST'])
def add_position():
    """添加持仓"""
    try:
        data = request.get_json()
        required_fields = ['knife', 'item', 'platform', 'price', 'time']

        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # 记录买入
        record_buy(
            knife=data['knife'],
            item_file=data['item'],
            platform=data['platform'],
            qty=data.get('qty', 1),
            price=data['price'],
            time_str=data['time'],
            root_dir=MODEL_DIR / "dataset/匕首"
        )

        return jsonify({
            "success": True,
            "message": "Position added successfully"
        })

    except Exception as e:
        logger.error(f"添加持仓时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/positions/<int:position_id>', methods=['DELETE'])
def remove_position(position_id):
    """删除持仓"""
    try:
        positions = load_positions()
        if position_id < 0 or position_id >= len(positions):
            return jsonify({"error": "Invalid position ID"}), 404

        removed_position = positions.pop(position_id)
        save_positions(positions)

        return jsonify({
            "success": True,
            "message": "Position removed successfully",
            "removed_position": removed_position
        })

    except Exception as e:
        logger.error(f"删除持仓时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/database/update', methods=['POST'])
def update_database():
    """更新数据库"""
    try:
        data = request.get_json() or {}
        api_token = data.get('api_token')

        if not api_token:
            return jsonify({"error": "API token required"}), 400

        # 创建数据库更新器
        updater = AutoDatabaseUpdater(api_token)

        # 运行数据库更新
        success = updater.run_build_database()

        if success:
            return jsonify({
                "success": True,
                "message": "Database updated successfully"
            })
        else:
            return jsonify({
                "success": False,
                "message": "Database update failed"
            }), 500

    except Exception as e:
        logger.error(f"更新数据库时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置信息"""
    return jsonify({
        "modes": list(MODE_MAP.keys()),
        "default_config": asdict(AnalysisConfig()),
        "available_categories": [
            "匕首", "步枪", "手枪", "手套", "探员"
        ]
    })

@app.route('/api/config/update', methods=['POST'])
def update_config():
    """更新配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No configuration data provided"}), 400

        # 这里可以添加配置持久化逻辑
        return jsonify({
            "success": True,
            "message": "Configuration updated successfully"
        })

    except Exception as e:
        logger.error(f"更新配置时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    """获取历史记录"""
    try:
        data = request.args
        limit = int(data.get('limit', 10))

        history_files = list((RESULTS_DIR / "history").glob("reco_*.json"))
        history_files.sort(reverse=True)  # 最新的在前

        history_data = []
        for file in history_files[:limit]:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    history_data.append({
                        "timestamp": file.stem.split("_", 1)[1],  # 提取时间戳
                        "mode": data.get('mode'),
                        "buy_candidates_count": len(data.get('buy_candidates', [])),
                        "watchlist_count": len(data.get('watchlist', [])),
                        "sell_advice_count": len(data.get('sell_advice_for_holdings', []))
                    })
            except Exception as e:
                logger.warning(f"读取历史文件 {file} 时出错: {e}")

        return jsonify({
            "history": history_data,
            "total_records": len(history_files)
        })

    except Exception as e:
        logger.error(f"获取历史记录时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/history/<timestamp>', methods=['GET'])
def get_history_detail(timestamp):
    """获取特定历史记录详情"""
    try:
        history_file = RESULTS_DIR / "history" / f"reco_{timestamp}.json"
        if not history_file.exists():
            return jsonify({"error": "History record not found"}), 404

        with open(history_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return jsonify(data)

    except Exception as e:
        logger.error(f"获取历史记录详情时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/analytics/trends', methods=['GET'])
def get_trends():
    """获取趋势分析"""
    try:
        data = request.args
        days = int(data.get('days', 7))

        # 获取最近N天的历史数据
        history_files = list((RESULTS_DIR / "history").glob("reco_*.json"))
        history_files.sort(reverse=True)

        trends_data = []
        for file in history_files[:days]:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    trends_data.append({
                        "date": file.stem.split("_", 1)[1][:8],  # YYYYMMDD
                        "buy_candidates": len(data.get('buy_candidates', [])),
                        "watchlist": len(data.get('watchlist', [])),
                        "sell_advice": len(data.get('sell_advice_for_holdings', []))
                    })
            except Exception as e:
                logger.warning(f"读取趋势数据时出错: {e}")

        return jsonify({
            "trends": trends_data,
            "period_days": days
        })

    except Exception as e:
        logger.error(f"获取趋势分析时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/export/data', methods=['GET'])
def export_data():
    """导出数据"""
    try:
        data = request.args
        export_type = data.get('type', 'current')

        if export_type == 'current':
            file_path = RESULTS_DIR / "realtime_reco.json"
        elif export_type == 'positions':
            positions = load_positions()
            return jsonify(positions)
        else:
            return jsonify({"error": "Invalid export type"}), 400

        if not file_path.exists():
            return jsonify({"error": "Data file not found"}), 404

        return send_file(file_path, as_attachment=True)

    except Exception as e:
        logger.error(f"导出数据时出错: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    """获取通知"""
    try:
        notifications = []

        # 检查系统状态
        status = get_system_status()
        if status.system_health != "healthy":
            notifications.append({
                "type": "warning",
                "title": "System Health Issue",
                "message": f"System health: {status.system_health}",
                "timestamp": datetime.now().isoformat()
            })

        # 检查持仓到期提醒
        positions = load_positions()
        for pos in positions:
            buy_time = datetime.strptime(pos['buy_time'], "%Y-%m-%d %H:%M")
            days_held = (datetime.now() - buy_time).days

            if days_held >= 7:  # T+7到期
                notifications.append({
                    "type": "info",
                    "title": "Position Ready for Sale",
                    "message": f"{pos['knife_type']} / {pos['item_name']} has reached T+7",
                    "timestamp": datetime.now().isoformat()
                })

        return jsonify({
            "notifications": notifications,
            "count": len(notifications)
        })

    except Exception as e:
        logger.error(f"获取通知时出错: {e}")
        return jsonify({"error": str(e)}), 500

# -------------------- 新增：列出全部监控物品 --------------------

@app.route('/api/items', methods=['GET'])
def list_items():
    """
    列出 dataset 中的所有监控物品（大类/刀型/CSV）
    返回示例：
    {
      "匕首": {
        "弯刀": [
          {"file":"6927_...csv","relative_path":"匕首/弯刀/6927_...csv","size_bytes":..., "mtime":"..."},
          ...
        ],
        "蝴蝶刀": [ ... ]
      },
      "步枪": { ... }
    }
    """
    try:
        data = _scan_items()
        return jsonify(data)
    except Exception as e:
        logger.error(f"/api/items 扫描失败: {e}")
        return jsonify({"error": str(e)}), 500

# -------------------- 新增：单个物品的K线 + MA --------------------

@app.route('/api/item/series', methods=['GET'])
def item_series():
    """
    获取某个CSV的时序数据（价格序列 + 聚合OHLC + 多条MA）
    查询方式（两选一）：
      1) ?path=匕首/弯刀/6927_...csv
      2) ?category=匕首&type=弯刀&file=6927_...csv
    额外参数：
      - platform=BUFF|YYYP（默认BUFF）
      - side=sell|buy（默认sell）
      - freq=H|D（默认H，按小时聚合K线；D为按天）
      - ma=24,72,168（可自定义窗口，单位=原始频率步长；默认 24,72,168）
      - start=ISO8601，end=ISO8601（时间范围过滤，可选）
    返回：
      {
        "meta": { "path": "...", "platform": "...", "side":"...", "freq":"H", "ma":[24,72,168], "rows": 123 },
        "price": [ {t, p}... ],
        "ohlc":  [ {t, o, h, l, c}... ],
        "ma":    { "24":[{t,ma}...], "72": [...], "168":[...] }
      }
    """
    try:
        # 路径参数
        path = request.args.get("path")
        if not path:
            category = request.args.get("category")
            typ = request.args.get("type")
            file = request.args.get("file")
            if not (category and typ and file):
                return jsonify({"error": "must provide path or (category&type&file)"}), 400
            path = f"{category}/{typ}/{file}"

        platform = (request.args.get("platform") or "BUFF").upper()
        side = (request.args.get("side") or "sell").lower()
        freq = (request.args.get("freq") or "H").upper()
        if freq not in ("H", "D"):
            return jsonify({"error": "freq must be H or D"}), 400

        ma_param = request.args.get("ma", "24,72,168")
        try:
            ma_windows = [int(x) for x in ma_param.split(",") if x.strip()]
            ma_windows = [w for w in ma_windows if w > 0]
            if not ma_windows:
                ma_windows = [24, 72, 168]
        except Exception:
            ma_windows = [24, 72, 168]

        start = request.args.get("start")
        end = request.args.get("end")

        # 读取 CSV
        df, price_map = _load_item_csv(path)

        # 选择价格列
        key = (platform, side)
        price_col = price_map.get(key)
        if not price_col or price_col not in df.columns:
            return jsonify({"error": f"price column not found for {platform} {side}"}), 400

        # 时间范围过滤
        df = _parse_time_range(df, start, end)

        # 构建结果
        data = _build_series_and_ohlc(df, price_col=price_col, freq=freq, ma_windows=ma_windows)

        return jsonify({
            "meta": {
                "path": path,
                "platform": platform,
                "side": side,
                "freq": freq,
                "ma": ma_windows,
                "rows": int(len(df)),
                "price_col": price_col
            },
            **data
        })

    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("/api/item/series 发生异常")
        return jsonify({"error": str(e)}), 500

# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# ==================== 启动脚本 ====================

if __name__ == '__main__':
    # 设置端口
    port = int(os.environ.get('PORT', 5000))
    # 启动服务器（开发用）；生产由 gunicorn 托管
    app.run(
        host='0.0.0.0',
        port=port,
        debug=True,
        threaded=True
    )
