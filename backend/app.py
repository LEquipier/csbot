#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T+7 饰品交易管理系统
基于Flask的Web应用，提供数据可视化、选品建议、持仓管理等功能
"""

import os
import sys
import json
import subprocess
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import glob

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入项目模块
from backend.CSQAQ import CsqaqClient
from backend.config import API_TOKEN

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 路径配置
BACKEND_DIR = Path(__file__).resolve().parent
MODEL_DIR = BACKEND_DIR / "Model"
DATASET_DIR = MODEL_DIR / "dataset"
RESULTS_DIR = MODEL_DIR / "results"
STATE_DIR = MODEL_DIR / "state"

# 确保目录存在
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

def create_app():
    """创建Flask应用"""
    app = Flask(__name__, 
               template_folder='../frontend/templates',
               static_folder='../frontend/static')
    
    # 配置应用
    app.config['SECRET_KEY'] = 't7-trading-system-2025'
    app.config['JSON_AS_ASCII'] = False
    
    # CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    return app

def create_client():
    """创建CSQAQ客户端"""
    try:
        client = CsqaqClient(api_token=API_TOKEN)
        logger.info("✅ CSQAQ客户端初始化成功")
        return client
    except Exception as e:
        logger.error(f"❌ CSQAQ客户端初始化失败: {e}")
        return None

# 创建应用和客户端
app = create_app()
client = create_client()

# ==================== 工具函数 ====================

def get_latest_model_result():
    """获取最新的模型分析结果"""
    result_file = RESULTS_DIR / "realtime_reco.json"
    if result_file.exists():
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取模型结果失败: {e}")
    return None

def get_model_history(days=7):
    """获取历史模型分析结果"""
    history_dir = RESULTS_DIR / "history"
    if not history_dir.exists():
        return []
    
    try:
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        
        history_files = []
        for history_file in history_dir.glob("reco_*.json"):
            try:
                # 从文件名提取时间戳
                timestamp_str = history_file.stem.split("_", 1)[1]
                file_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if file_date >= cutoff_date:
                    with open(history_file, 'r', encoding='utf-8') as f:
                        result = json.load(f)
                        result['file_date'] = file_date.strftime("%Y-%m-%d %H:%M:%S")
                        history_files.append(result)
            except Exception as e:
                logger.error(f"读取历史文件 {history_file.name} 失败: {e}")
        
        # 按时间倒序排列
        history_files.sort(key=lambda x: x['file_date'], reverse=True)
        return history_files
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}")
        return []

def get_positions():
    """获取持仓数据"""
    positions_file = STATE_DIR / "positions.json"
    if positions_file.exists():
        try:
            with open(positions_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取持仓数据失败: {e}")
    return []

def save_positions(positions):
    """保存持仓数据"""
    positions_file = STATE_DIR / "positions.json"
    try:
        with open(positions_file, 'w', encoding='utf-8') as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存持仓数据失败: {e}")
        return False

def run_model_analysis(mode="适中", topk=8, lookback=336):
    """运行模型分析"""
    try:
        cmd = [
            sys.executable,
            str(MODEL_DIR / "model.py"),
            "--mode", mode,
            "--topk", str(topk),
            "--lookback", str(lookback)
        ]
        
        result = subprocess.run(
            cmd,
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except Exception as e:
        return False, str(e)

def clean_item_name(file_name):
    """清理物品名称，去除数字和特殊字符，但保留Phase后面的数字"""
    import re
    
    # 移除文件扩展名
    name = file_name.replace('.csv', '')
    
    # 提取Phase信息
    phase_match = re.search(r'Phase(\d+)', name)
    phase_info = phase_match.group(0) if phase_match else ""
    
    # 移除所有数字
    name = re.sub(r'\d+', '', name)
    
    # 移除特殊字符，但保留中文、英文、空格
    name = re.sub(r'[^\u4e00-\u9fff\w\s]', '', name)
    
    # 清理多余空格和下划线
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'_+', ' ', name).strip()
    
    # 如果有Phase信息，添加到末尾
    if phase_info:
        name = name.replace('Phase', '').strip()  # 移除残留的Phase
        name = f"{name} {phase_info}"
    
    # 最终清理多余空格
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name

def get_dataset_stats():
    """获取数据集统计信息"""
    stats = {
        "total_files": 0,
        "total_records": 0,
        "knife_types": {},
        "latest_update": None
    }
    
    try:
        # 遍历所有CSV文件
        csv_files = list(DATASET_DIR.rglob("*.csv"))
        stats["total_files"] = len(csv_files)
        
        latest_time = None
        
        for csv_file in csv_files:
            try:
                # 获取刀型 - 从完整路径中提取
                path_parts = csv_file.parts
                if len(path_parts) >= 4 and path_parts[-3] == "匕首":
                    knife_type = path_parts[-2]  # 匕首目录下的子目录名
                else:
                    knife_type = csv_file.parent.name
                if knife_type not in stats["knife_types"]:
                    stats["knife_types"][knife_type] = {
                        "files": 0,
                        "records": 0
                    }
                
                stats["knife_types"][knife_type]["files"] += 1
                
                # 读取CSV文件
                df = pd.read_csv(csv_file, encoding='utf-8')
                records = len(df)
                stats["knife_types"][knife_type]["records"] += records
                stats["total_records"] += records
                
                # 更新时间
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    file_latest = df["date"].max()
                    if pd.notna(file_latest) and (latest_time is None or file_latest > latest_time):
                        latest_time = file_latest
                        
            except Exception as e:
                logger.error(f"处理文件 {csv_file} 失败: {e}")
                continue
        
        if latest_time:
            stats["latest_update"] = latest_time.strftime("%Y-%m-%d %H:%M")
            
    except Exception as e:
        logger.error(f"获取数据集统计失败: {e}")
    
    return stats

# ==================== 路由定义 ====================

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/api/dashboard')
def dashboard_data():
    """获取仪表板数据"""
    try:
        # 获取模型分析结果
        model_result = get_latest_model_result()
        
        # 获取数据集统计
        dataset_stats = get_dataset_stats()
        
        # 获取持仓数据
        positions = get_positions()
        
        return jsonify({
            'success': True,
            'model_result': model_result,
            'dataset_stats': dataset_stats,
            'positions': positions,
            'system_status': {
                'csqaq_client': client is not None,
                'last_update': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        })
    except Exception as e:
        logger.error(f"获取仪表板数据失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/model/analyze')
def run_analysis():
    """运行模型分析"""
    try:
        mode = request.args.get('mode', '适中')
        topk = int(request.args.get('topk', 8))
        lookback = int(request.args.get('lookback', 336))
        
        success, output = run_model_analysis(mode, topk, lookback)
        
        if success:
            # 获取最新结果
            result = get_latest_model_result()
            return jsonify({
                'success': True,
                'result': result,
                'output': output
            })
        else:
            return jsonify({
                'success': False,
                'error': output
            })
    except Exception as e:
        logger.error(f"运行模型分析失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/model/history')
def get_model_history_api():
    """获取历史模型分析结果"""
    try:
        days = int(request.args.get('days', 7))
        history = get_model_history(days)
        return jsonify({
            'success': True,
            'history': history
        })
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/positions')
def get_positions_api():
    """获取持仓数据"""
    try:
        positions = get_positions()
        return jsonify({
            'success': True,
            'positions': positions
        })
    except Exception as e:
        logger.error(f"获取持仓数据失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/positions/record', methods=['POST'])
def record_buy():
    """记录买入操作"""
    try:
        data = request.get_json()
        
        # 验证必需字段
        required_fields = ['knife_type', 'item_file', 'platform', 'qty', 'price', 'buy_time']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'缺少必需字段: {field}'})
        
        # 构建命令
        cmd = [
            sys.executable,
            str(MODEL_DIR / "model.py"),
            "--record-buy",
            "--knife", data['knife_type'],
            "--item", data['item_file'],
            "--platform", data['platform'],
            "--qty", str(data['qty']),
            "--price", str(data['price']),
            "--time", data['buy_time']
        ]
        
        # 执行命令
        result = subprocess.run(
            cmd,
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            # 重新获取持仓数据
            positions = get_positions()
            return jsonify({
                'success': True,
                'message': '买入记录成功',
                'positions': positions
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            })
    except Exception as e:
        logger.error(f"记录买入操作失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/dataset/items')
def get_dataset_items():
    """获取数据集中的物品列表"""
    try:
        knife_type = request.args.get('knife_type', '')
        # URL解码
        if knife_type:
            import urllib.parse
            knife_type = urllib.parse.unquote(knife_type)
        page = int(request.args.get('page', 1))
        size = int(request.args.get('size', 20))
        
        items = []
        
        # 构建搜索路径
        logger.info(f"DATASET_DIR: {DATASET_DIR}")
        if knife_type:
            knife_dir = DATASET_DIR / "匕首" / knife_type
            logger.info(f"搜索路径: {knife_dir}")
            logger.info(f"路径是否存在: {knife_dir.exists()}")
            csv_files = list(knife_dir.glob("*.csv")) if knife_dir.exists() else []
            logger.info(f"搜索刀型 {knife_type}，找到 {len(csv_files)} 个文件")
            if len(csv_files) == 0:
                # 列出匕首目录下的所有子目录
                dagger_dir = DATASET_DIR / "匕首"
                if dagger_dir.exists():
                    subdirs = [d.name for d in dagger_dir.iterdir() if d.is_dir()]
                    logger.info(f"匕首目录下的子目录: {subdirs}")
        else:
            csv_files = []
            for knife_dir in DATASET_DIR.glob("匕首/*"):
                if knife_dir.is_dir():
                    csv_files.extend(list(knife_dir.glob("*.csv")))
        
        # 分页
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        page_files = csv_files[start_idx:end_idx]
        
        for csv_file in page_files:
            try:
                # 读取CSV文件
                try:
                    df = pd.read_csv(csv_file, encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(csv_file, encoding='gbk')
                
                # 获取最新数据
                if len(df) > 0:
                    latest_row = df.iloc[-1]
                    
                    item_info = {
                        'file_name': csv_file.name,
                        'item_name': clean_item_name(csv_file.name),  # 清理后的物品名称
                        'knife_type': csv_file.parent.name,
                        'good_id': str(latest_row.get('good_id', '')),
                        'latest_date': str(latest_row.get('data', '')),  # 注意：CSV中是'data'列
                        'buff_sell_price': float(latest_row.get('BUFF_sell_price', 0)),
                        'yyyp_sell_price': float(latest_row.get('YYYP_sell_price', 0)),
                        'buff_buy_price': float(latest_row.get('BUFF_buy_price', 0)),
                        'yyyp_buy_price': float(latest_row.get('YYYP_buy_price', 0)),
                        'buff_sell_num': int(latest_row.get('BUFF_sell_num', 0)),
                        'yyyp_sell_num': int(latest_row.get('YYYP_sell_num', 0)),
                        'total_records': int(len(df))
                    }
                    items.append(item_info)
                    
            except Exception as e:
                logger.error(f"处理文件 {csv_file} 失败: {e}")
                continue
        
        return jsonify({
            'success': True,
            'items': items,
            'total': len(csv_files),
            'page': page,
            'size': size
        })
    except Exception as e:
        logger.error(f"获取数据集物品列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/dataset/item/<path:file_name>')
def get_item_data(file_name):
    """获取特定物品的详细数据"""
    try:
        knife_type = request.args.get('knife_type', '')
        # URL解码
        if knife_type:
            import urllib.parse
            knife_type = urllib.parse.unquote(knife_type)
        if not knife_type:
            return jsonify({'success': False, 'error': '需要指定刀型'})
        
        file_path = DATASET_DIR / "匕首" / knife_type / file_name
        
        if not file_path.exists():
            return jsonify({'success': False, 'error': '文件不存在'})
        
        # 读取CSV文件
        df = pd.read_csv(file_path, encoding='utf-8')
        
        # 转换数据格式
        data = []
        for _, row in df.iterrows():
            data.append({
                'date': row.get('date', ''),
                'buff_sell_price': row.get('BUFF_sell_price', 0),
                'yyyp_sell_price': row.get('YYYP_sell_price', 0),
                'buff_buy_price': row.get('BUFF_buy_price', 0),
                'yyyp_buy_price': row.get('YYYP_buy_price', 0),
                'buff_sell_num': row.get('BUFF_sell_num', 0),
                'yyyp_sell_num': row.get('YYYP_sell_num', 0),
                'buff_buy_num': row.get('BUFF_buy_num', 0),
                'yyyp_buy_num': row.get('YYYP_buy_num', 0),
                'buff_statistic': row.get('BUFF_statistic', 0),
                'yyyp_statistic': row.get('YYYP_statistic', 0)
            })
        
        return jsonify({
            'success': True,
            'data': data,
            'file_name': file_name,
            'knife_type': knife_type,
            'total_records': len(data)
        })
    except Exception as e:
        logger.error(f"获取物品数据失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/system/status')
def get_system_status():
    """获取系统状态"""
    try:
        # 检查auto_run进程
        auto_run_running = False
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'auto_run.py'],
                capture_output=True,
                text=True
            )
            auto_run_running = result.returncode == 0
        except:
            pass
        
        # 获取最新模型结果时间
        model_result = get_latest_model_result()
        last_analysis = model_result.get('asof') if model_result else None
        
        # 获取数据集统计
        dataset_stats = get_dataset_stats()
        
        return jsonify({
            'success': True,
            'status': {
                'csqaq_client': client is not None,
                'auto_run_running': auto_run_running,
                'last_analysis': last_analysis,
                'dataset_stats': dataset_stats,
                'system_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        })
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/system/start_auto_run')
def start_auto_run():
    """启动自动运行服务"""
    try:
        cmd = [
            sys.executable,
            str(BACKEND_DIR / "auto_run.py"),
            "--daemon"
        ]
        
        # 在后台启动
        subprocess.Popen(cmd, cwd=str(BACKEND_DIR))
        
        return jsonify({
            'success': True,
            'message': '自动运行服务已启动'
        })
    except Exception as e:
        logger.error(f"启动自动运行服务失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(error):
    """404错误处理"""
    return jsonify({'success': False, 'error': '接口不存在'}), 404

@app.errorhandler(500)
def internal_error(error):
    """500错误处理"""
    logger.error(f"服务器内部错误: {error}")
    return jsonify({'success': False, 'error': '服务器内部错误'}), 500

# ==================== 应用启动 ====================

if __name__ == '__main__':
    print("🚀 启动T+7饰品交易管理系统...")
    print("📊 访问地址: http://localhost:5050")
    print("🔧 调试模式: 已启用")
    app.run(host='0.0.0.0', port=5050, debug=True)
