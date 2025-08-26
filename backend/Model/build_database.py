# -*- coding: utf-8 -*-
"""
build_database.py

整合版本：支持串行和多线程两种模式

主要特点：
1. 严格1秒间隔API限制
2. 支持串行处理（稳定）和多线程处理（快速）
3. 智能重试和错误处理
4. 详细进度显示
5. 完全API合规

目标：
- 实时记录当前时刻的刀型数据
- 每次运行只记录当前数据，不获取历史数据
- 按照指定目录结构保存：dataset/匕首/匕首类型/皮肤类型.csv
- 如果文件不存在则创建，存在则追加新行

数据结构：
- 时间：基于北京时间的现实记录时间，精确到分钟
- BUFF_sell_price: BUFF平台最低售价
- YYYP_sell_price: YYYP平台最低售价  
- BUFF_buy_price: BUFF平台求购价格
- YYYP_buy_price: YYYP平台求购价格
- BUFF_sell_num: BUFF平台在售数量
- YYYP_sell_num: YYYP平台在售数量
- BUFF_buy_num: BUFF平台求购数量
- YYYP_buy_num: YYYP平台求购数量
- BUFF_statistic: BUFF平台成交量
- YYYP_statistic: YYYP平台成交量
- good_id: 商品ID


"""

import os
import json
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple, Union
from datetime import datetime, timezone, timedelta
import sys
import time
import glob
import re
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

# 导入CSQAQ客户端
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from CSQAQ import CsqaqClient
from config import API_TOKEN

# 需要过滤的关键词（在所有板块中都会被忽略）
FILTER_KEYWORDS = ["印花", "挂件", "音乐盒", "涂鸦"]

# 需要过滤的外观品质（在指定板块中会被忽略）
EXTERIOR_FILTER_KEYWORDS = ["战痕累累", "破损不堪"]

# 需要过滤的StatTrak物品（在指定板块中会被忽略）
STATTRAK_FILTER_CATEGORIES = ["匕首", "手枪", "步枪", "手套"]

# 排除关键词（避免交叉匹配）
EXCLUDE_KEYWORDS = {
    "刺刀": ["M9刺刀", "M9 刺刀"],  # 刺刀缓存排除M9刺刀
    "M9刺刀": ["刺刀"],  # M9刺刀缓存排除普通刺刀和自身（避免重复）
    "蝴蝶刀": [],  # 蝴蝶刀没有需要排除的
    "鲍伊猎刀": [],
    "弯刀": [],
    "折叠刀": [],
    "穿肠刀": [],
    "猎杀者匕首": [],
    "爪子刀": [],
    "暗影双匕": [],
    "短剑": [],
    "熊刀": [],
    "折刀": [],
    "锯齿爪刀": [],
    "海豹短刀": [],
    "系绳匕首": [],
    "求生匕首": [],
    "流浪者匕首": [],
    "骷髅匕首": [],
    "廓尔喀刀": [],
}

# 刀型关键词映射
KNIFE_KEYWORDS = {
    "蝴蝶刀": ["蝴蝶刀"],
    "鲍伊猎刀": ["鲍伊猎刀"],
    "弯刀": ["弯刀"],
    "折叠刀": ["折叠刀"],
    "穿肠刀": ["穿肠刀"],
    "猎杀者匕首": ["猎杀者匕首"],
    "M9刺刀": ["M9"],
    "刺刀": ["刺刀"],
    "爪子刀": ["爪子刀"],
    "暗影双匕": ["暗影双匕"],
    "短剑": ["短剑"],
    "熊刀": ["熊刀"],
    "折刀": ["折刀"],
    "锯齿爪刀": ["锯齿爪刀"],
    "海豹短刀": ["海豹短刀"],
    "系绳匕首": ["系绳匕首"],
    "求生匕首": ["求生匕首"],
    "流浪者匕首": ["流浪者匕首"],
    "骷髅匕首": ["骷髅匕首"],
    "廓尔喀刀": ["廓尔喀刀"]
}

# 新增物品类别关键词映射
ITEM_CATEGORIES = {
    # 匕首类别
    "匕首": KNIFE_KEYWORDS,
    
    # 探员类别
    "探员": {
        "探员": [
            "残酷的达里尔爵士（迈阿密）", "指挥官黛维达·费尔南德斯（护目镜）", "出逃的萨莉",
            "指挥官弗兰克·巴鲁德（湿袜）", "老 K", "残酷的达里尔爵士（聒噪）",
            "残酷的达里尔爵士（皇家）", "薇帕姐（革新派）", "D 中队军官",
            "残酷的达里尔爵士（头盖骨）", "陆军中尉普里米罗", "残酷的达里尔（穷鬼）",
            "残酷的达里尔爵士（沉默）", "小凯夫", "上校曼戈斯·达比西",
            "克拉斯沃特（三分熟）", "精锐捕兽者索尔曼", "爱娃特工",
            "中队长鲁沙尔·勒库托", "化学防害上尉", "捕兽者", "飞贼波兹曼",
            '"蓝莓" 铅弹', "遗忘者克拉斯沃特", "丛林反抗者", "海军上尉里克索尔",
            "捕兽者（挑衅者）", "军官雅克·贝尔特朗", '指挥官 梅 "极寒" 贾米森',
            "中尉法洛（抱树人）", "德国特种部队突击队", "中尉雷克斯·克里奇",
            "化学防害专家", '"医生" 罗曼诺夫', "生物防害专家",
            "海豹突击队第六分队士兵", "亚诺（野草）", "街头士兵", "军士长炸弹森",
            '约翰 "范·海伦" 卡斯克', "第一中尉法洛", "联邦调查局（FBI）特警", "精英穆哈里克先生",
            "军医少尉", "B 中队指挥官", "准尉", "迈克·赛弗斯", "黑狼",
            '"两次" 麦考伊', "红衫列赞", "德拉戈米尔", "准备就绪的列赞",
            "铅弹", "马尔库斯·戴劳", "凤凰战士", "奥西瑞斯", "马克西姆斯",
            "沙哈马特教授", "地面叛军"
        ],
    },
    
    # 手枪类别
    "手枪": {
        "USP 消音版": ["USP 消音版"],
        "格洛克 18 型": ["格洛克 18 型"],
        "沙漠之鹰": ["沙漠之鹰"],
    },
    
    # 步枪类别
    "步枪": {
        "AK-47": ["AK-47"],
        "M4A1": ["M4A1"],
        "M4A4": ["M4A4"],
        "AWP": ["AWP"],
    },
    
    # 手套类别
    "手套": {
        "运动手套": ["运动手套"],
        "专业手套": ["专业手套"],
        "摩托手套": ["摩托手套"],
    },
}

# 刀型模版配置 - 指定每个刀型要监测的特定模版
# 格式：{刀型名称: [模版名称列表]}
# 如果某个刀型不在这个配置中，则监测该刀型的所有模版
KNIFE_TEMPLATES = {
    "蝴蝶刀": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "伽马多普勒", # Gamma Doppler
        "虎牙",      # Tiger Tooth
        "黑色层压板", # Black Laminate
        "屠夫",      # Slaughter
        "传说",      # Legend
    ],
    "M9刺刀": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "伽马多普勒", # Gamma Doppler
        "虎牙",      # Tiger Tooth
        "黑色层压板", # Black Laminate
        "屠夫",      # Slaughter
        "传说",      # Legend
    ],
    "刺刀": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "伽马多普勒", # Gamma Doppler
        "虎牙",      # Tiger Tooth
        "黑色层压板", # Black Laminate
        "屠夫",      # Slaughter
        "传说",      # Legend
    ],
    "鲍伊猎刀": [
        "屠夫",      # Slaughter
    ],
    "弯刀": [
        "屠夫",      # Slaughter
    ],
    "折叠刀": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "伽马多普勒", # Gamma Doppler
        "虎牙",      # Tiger Tooth
        "黑色层压板", # Black Laminate
        "屠夫",      # Slaughter
        "传说",      # Legend
    ],
    "穿肠刀": [
        "屠夫",      # Slaughter
    ],
    "猎杀者匕首": [
        "屠夫",      # Slaughter
    ],
    "爪子刀": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "伽马多普勒", # Gamma Doppler
        "虎牙",      # Tiger Tooth
        "黑色层压板", # Black Laminate
        "屠夫",      # Slaughter
        "传说",      # Legend
    ],
    "暗影双匕": [
        "屠夫",      # Slaughter
    ],
    "短剑": [
        "多普勒",    # Doppler
        "虎牙",      # Tiger Tooth
        "屠夫",      # Slaughter
    ],
    "熊刀": [
        "屠夫",      # Slaughter
    ],
    "折刀": [
        "屠夫",      # Slaughter
    ],
    "锯齿爪刀": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "虎牙",      # Tiger Tooth
        "屠夫",      # Slaughter
    ],
    "海豹短刀": [
        "屠夫",      # Slaughter
    ],
    "系绳匕首": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "虎牙",      # Tiger Tooth
        "屠夫",      # Slaughter
    ],
    "求生匕首": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "虎牙",      # Tiger Tooth
        "屠夫",      # Slaughter
    ],
    "流浪者匕首": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "虎牙",      # Tiger Tooth
        "屠夫",      # Slaughter
    ],
    "骷髅匕首": [
        "渐变之色",  # Fade
        "多普勒",    # Doppler
        "虎牙",      # Tiger Tooth
        "屠夫",      # Slaughter
    ],
    "廓尔喀刀": [
        "屠夫",      # Slaughter
    ],
}

# 新增类别的模版配置
ITEM_TEMPLATES = {
    # 探员模版配置
    "探员": [
            "残酷的达里尔爵士（迈阿密）", "指挥官黛维达·费尔南德斯（护目镜）", "出逃的萨莉",
            "指挥官弗兰克·巴鲁德（湿袜）", "老 K", "残酷的达里尔爵士（聒噪）",
            "残酷的达里尔爵士（皇家）", "薇帕姐（革新派）", "D 中队军官",
            "残酷的达里尔爵士（头盖骨）", "陆军中尉普里米罗", "残酷的达里尔（穷鬼）",
            "残酷的达里尔爵士（沉默）", "小凯夫", "上校曼戈斯·达比西",
            "克拉斯沃特（三分熟）", "精锐捕兽者索尔曼", "爱娃特工",
            "中队长鲁沙尔·勒库托", "化学防害上尉", "捕兽者", "飞贼波兹曼",
            '"蓝莓" 铅弹', "遗忘者克拉斯沃特", "丛林反抗者", "海军上尉里克索尔",
            "捕兽者（挑衅者）", "军官雅克·贝尔特朗", '指挥官 梅 "极寒" 贾米森',
            "中尉法洛（抱树人）", "德国特种部队突击队", "中尉雷克斯·克里奇",
            "化学防害专家", '"医生" 罗曼诺夫', "生物防害专家",
            "海豹突击队第六分队士兵", "亚诺（野草）", "街头士兵", "军士长炸弹森",
            '约翰 "范·海伦" 卡斯克', "第一中尉法洛", "联邦调查局（FBI）特警", "精英穆哈里克先生",
            "军医少尉", "B 中队指挥官", "准尉", "迈克·赛弗斯", "黑狼",
            '"两次" 麦考伊', "红衫列赞", "德拉戈米尔", "准备就绪的列赞",
            "铅弹", "马尔库斯·戴劳", "凤凰战士", "奥西瑞斯", "马克西姆斯",
            "沙哈马特教授", "地面叛军"
    ],
    
    # 手枪模版配置
    "USP 消音版": [
        "银装素裹",
        "锁定",
        "猎户",
        "黑水",
        "血刃",
        "黑色魅影",
        "印花集", # Printstream
        "倒吊人", # Hanged Man
        "次时代", # Next Generation
        "枪响人亡", # Gunsmoke
        "脑洞大开", # Mind the Gap
        "破鄂者", # Jawbreaker
    ],
    "格洛克 18 型": [
        "忍瞳", # Ninjas in Pyjamas
        "伽马多普勒", # Gamma Doppler
        "子弹皇后", # Bullet Queen
        "水灵", # Water Elemental
        "摩登时代", # Modern Warfare
        "大金牙", # Big Badger
        "黑色魅影", # Black Laminate
        "零食派对", # Snack Attack
        "渐变之色", # Fade
        "AXIA",
        "荒野反叛",
        
    ],
    "沙漠之鹰": [
        "炽烈之炎", # Blaze
        "翡翠巨蟒", # Emerald Python
        "沙漠之狐", # Desert Fox
        "印花集", # Printstream
        "波涛纵横", # Ripple
        "星辰拱廊", # Starlight Guard
        "钴蓝禁锢", # Cobalt Obliteration
        "红色代号", # Redline
        "马珀丽", # Marple
    ],
    
    # 步枪模版配置
    "AK-47": [
        "野荷",
        "水栽竹",
        "黄金藤蔓",
        "火蛇",
        "火神",
        "怪兽在B",
        "燃料喷射器",
        "红线",
        "血腥运动",
        "新红浪潮",
        "传承",
        "抽象派 1337",
        "荒野反叛",
        "皇后",
        "二西莫夫",
        "X射线",
        "深海复仇",
        "卡特尔",
        "混沌点阵",
        "美洲猛虎",
        "美洲豹",
        "霓虹骑士",
        "夜愿",
        "轨道 Mk01",
        "一发入魂",
        "局外人",
        
    ],
    "M4A1": [
        "赤红新星",
        "冒险家乐园",
        "紧迫危机",
        "澜磷",
        "渐变之色",
        "伊卡洛斯的陨落",
        "印花集",
        "蒸汽波",
        "二号玩家",
        "次时代",
        "原子合金",
        "女火神之炽焰",
        "梦魇",
        
    ],
    "M4A4": [
        "破晓",
        "荷鲁斯之眼",
        "合纵",
        "二西莫夫",
        "喧嚣杀戮",
        "炼狱之火",
        "地狱烈焰",
        "皇帝",
        "皇家圣骑士",
        "反冲精英",
        "黑色魅影",
        "活色生香",
    ],
    "AWP": [
        "九头金蛇",
        "雷击",
        "鬼退治",
        "二西莫夫",
        "红线",
        "印花集",
        "镀铬大炮",
        "黑色魅影",
    ],
    
    # 手套模版配置
    "运动手套": [
        "树篱迷宫",
        "潘多拉之盒",
        "超导体",
        "迈阿密风云",
        "干旱",
        "弹弓",
        "夜行衣",
        "双栖",
        "欧米伽",
    ],
    "专业手套": [
        "深红和服",
        "翠绿之网",
        "元勋",
        "渐变之色",
        "老虎精英",
    ],
    "摩托手套": [
        "薄荷",
        "清凉薄荷",
        "*嘣！*",
        "*嘭！*",
    ],
}



# API合规配置
REQUEST_INTERVAL = 0.5  # 严格1秒间隔
MAX_RETRIES = 5  # 最大重试次数
RATE_LIMIT_DELAY = 5  # 遇到限流时的延迟

# 多线程配置
DEFAULT_MAX_WORKERS = 4  # 默认处理线程数

# 平台配置
PLATFORM_MAP = {1: "BUFF", 2: "YYYP"}
DEFAULT_PLATFORMS = [1, 2]  # 只使用BUFF和YYYP

# 数据获取配置
MIN_PRICE_THRESHOLD = 100  # 最低价格阈值

class ItemDatabaseBuilder:
    def __init__(self, api_token: str, use_multithreading: bool = False, max_workers: int = DEFAULT_MAX_WORKERS, enable_template_filter: bool = True):
        self.client = CsqaqClient(api_token=api_token)
        self.api_token = api_token
        self.use_multithreading = use_multithreading
        self.max_workers = max_workers
        self.enable_template_filter = enable_template_filter
        
        # 获取北京时间
        self.current_time = self.get_beijing_time()
        
        # 设置缓存和数据集目录，都在Model目录下
        base_dir = os.path.dirname(__file__)
        self.cache_dir = os.path.join(base_dir, "cache")
        self.dataset_dir = os.path.join(base_dir, "dataset")
        
        # 确保目录存在
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        if not os.path.exists(self.dataset_dir):
            os.makedirs(self.dataset_dir)
        
        # 统计信息
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'rate_limit_hits': 0,
            'start_time': time.time(),
            'last_request_time': 0
        }
        
        # 多线程相关
        if self.use_multithreading:
            self.lock = threading.Lock()
            self.file_locks = {}  # 文件写入锁
    
    def get_beijing_time(self) -> str:
        """获取北京时间"""
        # 获取UTC时间
        utc_now = datetime.now(timezone.utc)
        # 北京时间是UTC+8
        beijing_tz = timezone(timedelta(hours=8))
        beijing_time = utc_now.astimezone(beijing_tz)
        return beijing_time.strftime("%Y-%m-%d %H:%M")
    
    def enforce_rate_limit(self):
        """强制执行API频率限制"""
        if self.use_multithreading:
            with self.lock:
                current_time = time.time()
                time_since_last = current_time - self.stats['last_request_time']
                
                if time_since_last < REQUEST_INTERVAL:
                    sleep_time = REQUEST_INTERVAL - time_since_last
                    print(f"    ⏳ 等待 {sleep_time:.1f} 秒以符合API限制...")
                    time.sleep(sleep_time)
                
                self.stats['last_request_time'] = time.time()
        else:
            current_time = time.time()
            time_since_last = current_time - self.stats['last_request_time']
            
            if time_since_last < REQUEST_INTERVAL:
                sleep_time = REQUEST_INTERVAL - time_since_last
                print(f"    ⏳ 等待 {sleep_time:.1f} 秒以符合API限制...")
                time.sleep(sleep_time)
            
            self.stats['last_request_time'] = time.time()
        
    def ensure_dir(self, path: str):
        """确保目录存在"""
        os.makedirs(path, exist_ok=True)
    
    def get_cache_file_path(self, item_type: str) -> str:
        """获取缓存文件路径"""
        # 获取物品类型所属的类别
        category = self.get_category_for_item_type(item_type)
        
        # 缓存文件路径：cache/类别/物品类型_items_cache.json
        return os.path.join(self.cache_dir, category, f"{item_type}_items_cache.json")
    
    def load_cached_items(self, item_type: str) -> Dict[str, Any]:
        """加载缓存的商品信息"""
        cache_file = self.get_cache_file_path(item_type)
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    print(f"✅ 从缓存加载 {len(cache_data.get('items', {}))} 个 {item_type} 商品")
                    return cache_data
            except Exception as e:
                print(f"❌ 加载缓存失败：{e}")
        return {}
    
    def save_cached_items(self, item_type: str, items_info: Dict[str, Any]):
        """保存商品信息到缓存"""
        cache_file = self.get_cache_file_path(item_type)
        
        # 确保目录存在
        cache_dir = os.path.dirname(cache_file)
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_data = {
            "item_type": item_type,
            "category": self.get_category_for_item_type(item_type),
            "update_time": self.current_time,
            "items": items_info
        }
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"✅ 缓存 {len(items_info)} 个 {item_type} 商品信息")
        except Exception as e:
            print(f"❌ 保存缓存失败：{e}")
    
    def should_filter_item(self, item_name: str, item_type: str) -> bool:
        """判断是否应该过滤掉某个物品"""
        item_name_lower = item_name.lower()
        
        # 1. 过滤掉包含基础过滤关键词的物品（精确匹配，避免误过滤）
        # 检查是否包含独立的过滤关键词，而不是作为其他词的一部分
        for keyword in FILTER_KEYWORDS:
            # 使用更精确的匹配，避免误过滤包含这些关键词的正常皮肤名称
            if keyword in item_name:
                # 检查是否是独立的过滤关键词，而不是皮肤名称的一部分
                if keyword == "印花" and "印花集" in item_name:
                    # "印花集"是正常皮肤名称，不应该被过滤
                    continue
                if keyword == "挂件" and ("挂件" in item_name and len(item_name.split("挂件")) > 2):
                    # 如果"挂件"出现在多个地方，可能是正常皮肤名称的一部分
                    continue
                return True
        
        # 2. 过滤掉StatTrak物品（仅在指定类别中）
        category = self.get_category_for_item_type(item_type)
        if category in STATTRAK_FILTER_CATEGORIES:
            if "stattrak" in item_name_lower or "stat trak" in item_name_lower:
                return True
        
        # 3. 过滤掉特定外观品质的物品（在指定类别中）
        exterior_filter_categories = ["匕首", "手枪", "步枪", "手套"]
        if category in exterior_filter_categories:
            for keyword in EXTERIOR_FILTER_KEYWORDS:
                if keyword in item_name:
                    return True
        
        return False
    
    def search_and_cache_items(self, item_type: str, keywords: List[str]) -> Dict[str, Any]:
        """搜索并缓存商品信息（API合规版本）"""
        print(f"🔍 搜索 {item_type} 商品（API合规模式）...")
        
        all_items_info = {}
        filtered_count = 0
        
        # 使用多个关键词搜索
        for keyword in keywords:
            print(f"  搜索关键词：{keyword}")
            
            # 分页获取所有商品
            page_index = 1
            while True:
                try:
                    # 强制执行频率限制
                    self.enforce_rate_limit()
                    
                    response = self.client.get_good_id(page_index=page_index, page_size=50, search=keyword)
                    data = response.get("data", {})
                    
                    # API返回的数据结构是 data.data，包含商品字典
                    goods_dict = data.get("data", {})
                    
                    if not goods_dict:
                        break
                    
                    # 提取商品信息
                    for good_id, item in goods_dict.items():
                        if good_id:
                            item_name = item.get("name", "")
                            
                            # 使用新的过滤函数
                            if self.should_filter_item(item_name, item_type):
                                filtered_count += 1
                                continue
                                
                            all_items_info[str(good_id)] = {
                                "good_id": str(good_id),
                                "name": item_name,
                                "market_hash_name": item.get("market_hash_name", ""),
                                "keyword": keyword
                            }
                    
                    page_index += 1
                    
                    # 限制搜索页数，避免过多请求
                    if page_index > 5:
                        break
                        
                except Exception as e:
                    print(f"  获取第{page_index}页失败：{e}")
                    break
        
        print(f"  总共找到 {len(all_items_info)} 个 {item_type} 相关商品")
        if filtered_count > 0:
            print(f"  过滤掉 {filtered_count} 个不符合条件的商品")
        
        # 保存到缓存
        self.save_cached_items(item_type, all_items_info)
        
        return all_items_info
    
    def safe_get(self, d: Dict, *ks, default=None):
        """安全获取嵌套字典值"""
        cur = d
        for k in ks:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur
    
    def get_single_good_detail(self, good_id: str) -> Dict[str, Any]:
        """获取单个商品详情（严格遵循API限制）"""
        for attempt in range(MAX_RETRIES):
            try:
                # 强制执行频率限制
                self.enforce_rate_limit()
                
                print(f"    📡 获取商品 {good_id} 详情... (尝试 {attempt + 1}/{MAX_RETRIES})")
                detail = self.client.good_detail(good_id)
                
                if self.use_multithreading:
                    with self.lock:
                        self.stats['successful_requests'] += 1
                else:
                    self.stats['successful_requests'] += 1
                    
                print(f"    ✅ 商品 {good_id} 获取成功")
                return detail
                
            except Exception as e:
                error_str = str(e).lower()
                
                if self.use_multithreading:
                    with self.lock:
                        self.stats['failed_requests'] += 1
                else:
                    self.stats['failed_requests'] += 1
                
                # 检查是否为限流错误
                if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                    if self.use_multithreading:
                        with self.lock:
                            self.stats['rate_limit_hits'] += 1
                    else:
                        self.stats['rate_limit_hits'] += 1
                        
                    print(f"    ⚠️ 商品 {good_id} 遇到限流，等待 {RATE_LIMIT_DELAY} 秒...")
                    time.sleep(RATE_LIMIT_DELAY)
                else:
                    # 其他错误，使用指数退避
                    wait_time = min(2 ** attempt, 10)  # 最大等待10秒
                    print(f"    ⚠️ 商品 {good_id} 请求失败：{e}")
                    print(f"    ⏳ 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                
                if attempt == MAX_RETRIES - 1:
                    print(f"    ❌ 商品 {good_id} 重试 {MAX_RETRIES} 次后仍然失败")
                    return None
        
        return None
    
    def get_all_good_details(self, good_ids: List[str]) -> Dict[str, Any]:
        """获取所有商品详情（串行处理，严格遵循API限制）"""
        print(f"📡 开始获取 {len(good_ids)} 个商品详情（API合规模式）...")
        print(f"⚙️ 配置：严格1秒间隔，无并发请求")
        
        results = {}
        start_time = time.time()
        
        for i, good_id in enumerate(good_ids):
            print(f"\n📊 进度：{i+1}/{len(good_ids)} ({((i+1)/len(good_ids)*100):.1f}%)")
            
            detail = self.get_single_good_detail(good_id)
            if detail:
                results[good_id] = detail
            
            self.stats['total_requests'] += 1
            
            # 显示预估剩余时间
            if i > 0:
                elapsed_time = time.time() - start_time
                avg_time_per_request = elapsed_time / (i + 1)
                remaining_requests = len(good_ids) - (i + 1)
                estimated_remaining_time = remaining_requests * avg_time_per_request
                
                print(f"    ⏱️  已耗时：{elapsed_time:.1f}秒")
                print(f"    📈 平均每请求：{avg_time_per_request:.1f}秒")
                print(f"    ⏰ 预估剩余：{estimated_remaining_time:.1f}秒")
        
        end_time = time.time()
        total_time = end_time - start_time
        
        print(f"\n✅ 商品详情获取完成")
        print(f"  - 成功获取：{len(results)}/{len(good_ids)} 个商品")
        print(f"  - 成功率：{len(results)/len(good_ids)*100:.1f}%")
        print(f"  - 总耗时：{total_time:.1f}秒")
        print(f"  - 平均耗时：{total_time/len(good_ids):.1f}秒/商品")
        print(f"  - 限流次数：{self.stats['rate_limit_hits']}")
        
        return results
    
    def get_vol_data_info(self) -> Dict[str, int]:
        """获取成交量数据信息"""
        print("📊 获取成交量数据...")
        self.enforce_rate_limit()
        
        try:
            url = "https://api.csqaq.com/api/v1/info/vol_data_info"
            headers = {
                'ApiToken': self.api_token,
                'Content-Type': 'application/json'
            }
            
            import requests
            response = requests.post(url, headers=headers, json={}, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and isinstance(data['data'], list):
                    vol_data = {}
                    for item in data['data']:
                        good_id = str(item.get('good_id', ''))
                        statistic = item.get('statistic', 0)
                        vol_data[good_id] = statistic
                    
                    print(f"✅ 成功获取 {len(vol_data)} 个物品的成交量数据")
                    return vol_data
                else:
                    print("❌ 成交量数据格式错误")
                    return {}
            else:
                print(f"❌ 获取成交量数据失败: {response.status_code}")
                return {}
                
        except Exception as e:
            print(f"❌ 获取成交量数据异常: {e}")
            return {}
    
    def get_item_template(self, item_name: str) -> str:
        """从商品名称中识别模版类型"""
        item_name_lower = item_name.lower()
        
        # 特殊处理探员：探员是具体的物品名称，直接返回物品名称
        # 检查是否包含探员相关关键词
        if any(keyword in item_name_lower for keyword in ["agent", "探员", "t agent", "ct agent"]):
            # 对于探员，直接返回物品名称作为模板
            return item_name
        
        # 对于其他物品类型，直接返回物品名称作为模板
        # 因为我们已经有了详细的模板配置，不需要关键词映射
        return item_name
    
    def filter_items_by_templates(self, item_type: str, all_items_info: Dict[str, Any], verbose: bool = True) -> Dict[str, Any]:
        """根据模版配置筛选商品"""
        if not self.enable_template_filter:
            if verbose:
                print(f"📝 模版筛选已禁用，保留所有商品")
            return all_items_info
        
        # 检查是否在匕首模版配置中
        if item_type in KNIFE_TEMPLATES:
            target_templates = KNIFE_TEMPLATES[item_type]
            if verbose:
                print(f"🎯 {item_type} 匕首模版筛选：{', '.join(target_templates)}")
        # 检查是否在物品模版配置中
        elif item_type in ITEM_TEMPLATES:
            target_templates = ITEM_TEMPLATES[item_type]
            if verbose:
                print(f"🎯 {item_type} 物品模版筛选：{', '.join(target_templates)}")
        else:
            if verbose:
                print(f"📝 {item_type} 未配置模版筛选，保留所有商品")
            return all_items_info
        
        filtered_items = {}
        template_stats = {}
        
        for good_id, item_info in all_items_info.items():
            item_name = item_info.get("name", "")
            
            # 首先应用过滤逻辑，过滤掉不应该的商品
            if self.should_filter_item(item_name, item_type):
                continue
            
            # 特殊处理探员类别：使用包含匹配而不是精确匹配
            if item_type == "探员":
                matched = False
                for target_template in target_templates:
                    if target_template in item_name:
                        filtered_items[good_id] = item_info
                        template_stats[target_template] = template_stats.get(target_template, 0) + 1
                        matched = True
                        break
            else:
                # 其他类别：在物品名称中搜索模板关键词
                matched = False
                for target_template in target_templates:
                    if target_template.lower() in item_name.lower():
                        filtered_items[good_id] = item_info
                        template_stats[target_template] = template_stats.get(target_template, 0) + 1
                        matched = True
                        break
        
        if verbose:
            print(f"✅ 模版筛选结果：")
            print(f"  - 原始商品数量：{len(all_items_info)}")
            print(f"  - 筛选后数量：{len(filtered_items)}")
            print(f"  - 筛选率：{len(filtered_items)/len(all_items_info)*100:.1f}%")
            
            for template, count in template_stats.items():
                print(f"  - {template}：{count} 个")
        
        return filtered_items
    
    def is_doppler_item(self, item_name: str) -> Tuple[bool, str, str]:
        """判断是否为多普勒系列物品，返回(是否是多普勒, 多普勒类型, 具体Phase)"""
        item_name_lower = item_name.lower()
        
        # 检查是否为多普勒
        if "doppler" in item_name_lower:
            # 检查是否为伽马多普勒
            if "gamma" in item_name_lower:
                doppler_type = "伽马多普勒"
            else:
                doppler_type = "多普勒"
            
            # 检查具体Phase
            if "ruby" in item_name_lower or "红宝石" in item_name_lower:
                return True, doppler_type, "红宝石"
            elif "sapphire" in item_name_lower or "蓝宝石" in item_name_lower:
                return True, doppler_type, "蓝宝石"
            elif "emerald" in item_name_lower or "绿宝石" in item_name_lower:
                return True, doppler_type, "绿宝石"
            elif "phase 1" in item_name_lower or "p1" in item_name_lower:
                return True, doppler_type, "Phase1"
            elif "phase 2" in item_name_lower or "p2" in item_name_lower:
                return True, doppler_type, "Phase2"
            elif "phase 3" in item_name_lower or "p3" in item_name_lower:
                return True, doppler_type, "Phase3"
            elif "phase 4" in item_name_lower or "p4" in item_name_lower:
                return True, doppler_type, "Phase4"
            else:
                return True, doppler_type, "Phase1"
        
        return False, "", ""
    
    def get_doppler_phases_from_api(self, good_detail: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从API返回的good_detail中获取多普勒Phase信息"""
        dpl_data = self.safe_get(good_detail, "data", "dpl", default=[])
        if not dpl_data:
            return []
        
        phases = []
        for phase_info in dpl_data:
            phase = {
                "key": phase_info.get("key"),
                "label": phase_info.get("label"),
                "value": phase_info.get("value"),
                "def_index": phase_info.get("def_index"),
                "paint_index": phase_info.get("paint_index"),
                "short_name_en": phase_info.get("short_name_en"),
                "buff_sell_price": phase_info.get("buff_sell_price"),
                "buff_buy_price": phase_info.get("buff_buy_price")
            }
            phases.append(phase)
        
        return phases
    
    def split_doppler_items(self, items: List[Dict[str, Any]], good_details: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将多普勒系列物品分割为独立的Phase物品"""
        split_items = []
        
        for item in items:
            good_id = item.get("good_id", "")
            item_name = item.get("name", "")
            
            # 检查API返回的good_detail中是否有dpl字段
            if good_id in good_details:
                detail = good_details[good_id]
                dpl_phases = self.get_doppler_phases_from_api(detail)
                
                if dpl_phases:
                    # 这是一个多普勒物品，需要分割
                    print(f"  🔪 发现多普勒物品：{item_name}")
                    print(f"     包含 {len(dpl_phases)} 个Phase")
                    
                    for phase_info in dpl_phases:
                        phase_label = phase_info.get("label", "")
                        phase_value = phase_info.get("value", "")
                        
                        # 创建新的物品记录
                        new_item = item.copy()
                        new_item["original_name"] = item_name
                        new_item["original_good_id"] = good_id
                        new_item["name"] = f"{item_name} ({phase_label})"
                        new_item["doppler_phase"] = phase_label
                        new_item["doppler_value"] = phase_value
                        new_item["good_id"] = f"{good_id}_{phase_label}"
                        
                        # 添加Phase特定的价格信息
                        if phase_info.get("buff_sell_price"):
                            new_item["buff_sell_price"] = phase_info["buff_sell_price"]
                        if phase_info.get("buff_buy_price"):
                            new_item["buff_buy_price"] = phase_info["buff_buy_price"]
                        
                        # 添加Phase特定的统计信息
                        statistic_list = self.safe_get(detail, "data", "statistic_list", default=[])
                        for stat in statistic_list:
                            if stat.get("name") == phase_label:
                                new_item["phase_statistic"] = stat.get("statistic", 0)
                                new_item["phase_statistic_at"] = stat.get("statistic_at", "")
                                break
                        
                        split_items.append(new_item)
                        print(f"     ✅ 创建Phase：{phase_label} (ID: {new_item['good_id']})")
                else:
                    # 非多普勒物品直接添加
                    split_items.append(item)
            else:
                # 如果没有找到good_detail，使用原来的名称匹配方法
                is_doppler, doppler_type, phase = self.is_doppler_item(item_name)
                if is_doppler:
                    new_item = item.copy()
                    new_item["original_name"] = item_name
                    new_item["name"] = f"{item_name} ({doppler_type} {phase})"
                    new_item["doppler_type"] = doppler_type
                    new_item["doppler_phase"] = phase
                    new_item["good_id"] = f"{item['good_id']}_{phase}"
                    split_items.append(new_item)
                else:
                    split_items.append(item)
        
        return split_items
    
    def fetch_knife_universe(self, item_type: str, keywords: List[str], 
                           max_pages: int = 8, page_size: int = 50, 
                           test_mode: bool = False, max_items: int = None) -> List[str]:
        """获取指定物品类型的商品ID列表"""
        print(f"🔍 搜索 {item_type} 商品...")
        
        results = []
        seen = set()
        
        for keyword in keywords:
            print(f"  搜索关键词：{keyword}")
            for page in range(1, max_pages + 1):
                try:
                    resp = self.client.get_good_id(keyword, page_index=page, page_size=page_size)
                    data = self.safe_get(resp, "data", "data", default={})
                    if not data:
                        break
                    
                    for gid_str, rec in data.items():
                        name = rec.get("name", rec.get("market_hash_name", "")).lower()
                        if any(kw.lower() in name for kw in keywords):
                            if gid_str not in seen:
                                seen.add(gid_str)
                                results.append(gid_str)
                    
                    time.sleep(1)  # 避免API限制
                    
                except Exception as e:
                    print(f"    搜索失败：{e}")
                    continue
        
        # 价格过滤
        filtered = []
        print(f"  价格过滤 {len(results)} 个候选商品...")
        
        for i, gid in enumerate(results):
            if test_mode and max_items is not None and i >= max_items:  # 测试模式处理指定数量的物品
                break
                
            if i % 10 == 0:
                print(f"    处理进度：{i+1}/{min(len(results), 3 if test_mode else len(results))}")
            
            try:
                det = self.client.good_detail(gid)
                info = self.safe_get(det, "data", default={})
                
                # 尝试多个价格字段
                candidates = []
                for k in ["buff_sell_price", "yyyp_sell_price",
                          "buffBuyPrice", "yyypBuyPrice",
                          "buffSellPrice", "yyypSellPrice"]:
                    v = info.get(k)
                    if v is not None:
                        try:
                            v = float(v)
                        except:
                            v = np.nan
                        if np.isfinite(v) and v > 0:
                            candidates.append(v)
                
                if not candidates:
                    # batch_price 再试
                    mhn = self.safe_get(info, "goods_info", "market_hash_name", default=None)
                    if mhn:
                        bp = self.client.batch_price([mhn])
                        succ = self.safe_get(bp, "data", "success", default={})
                        ditem = succ.get(mhn, {})
                        for k in ["buffSellPrice", "yyypSellPrice"]:
                            v = ditem.get(k)
                            if v is not None:
                                try:
                                    v = float(v)
                                except:
                                    v = np.nan
                                if np.isfinite(v) and v > 0:
                                    candidates.append(v)
                
                max_price = max(candidates) if candidates else 0
                if max_price >= MIN_PRICE_THRESHOLD:
                    filtered.append(gid)
                
                time.sleep(0.5)  # 避免API限制
                
            except Exception as e:
                print(f"    获取商品 {gid} 详情失败：{e}")
                continue
        
        # 测试模式：随机选择一个商品
        if test_mode and filtered:
            selected = random.choice(filtered)
            print(f"🎲 测试模式：随机选择 {item_type} 的一个商品：{selected}")
            filtered = [selected]
        
        print(f"✅ {item_type} 找到 {len(filtered)} 个符合条件的商品")
        return filtered
    
    def get_current_item_data(self, good_id: str, vol_data: Dict[str, int]) -> Dict[str, Any]:
        """获取单个商品的当前数据"""
        try:
            # 获取商品详情
            detail = self.client.good_detail(good_id)
            info = detail.get("data", {})
            goods_info = info.get("goods_info", {})
            
            # 基础信息
            item_data = {
                "time": self.get_beijing_time(),
                "good_id": str(good_id),
                "name": goods_info.get("name", ""),
                "market_hash_name": goods_info.get("market_hash_name", ""),
                "exterior": goods_info.get("exterior", ""),
                "collection": goods_info.get("collection", "")
            }
            
            # 使用batch_price接口获取价格和数量信息
            mhn = goods_info.get("market_hash_name")
            if mhn:
                try:
                    bp = self.client.batch_price([mhn])
                    succ = bp.get("data", {}).get("success", {})
                    if mhn in succ:
                        ditem = succ[mhn]
                        
                        # 根据API文档，字段名是驼峰命名法
                        item_data["BUFF_sell_price"] = ditem.get("buffSellPrice", np.nan)
                        item_data["YYYP_sell_price"] = ditem.get("yyypSellPrice", np.nan)
                        item_data["BUFF_buy_price"] = ditem.get("buffBuyPrice", np.nan)  # 可能不存在
                        item_data["YYYP_buy_price"] = ditem.get("yyypBuyPrice", np.nan)  # 可能不存在
                        item_data["BUFF_sell_num"] = ditem.get("buffSellNum", np.nan)
                        item_data["YYYP_sell_num"] = ditem.get("yyypSellNum", np.nan)
                        item_data["BUFF_buy_num"] = ditem.get("buffBuyNum", np.nan)  # 可能不存在
                        item_data["YYYP_buy_num"] = ditem.get("yyypBuyNum", np.nan)  # 可能不存在
                        
                        print(f"    ✅ 从batch_price获取到数据")
                    else:
                        print(f"    ❌ 在batch_price中未找到商品: {mhn}")
                        # 设置默认值
                        for field in ["BUFF_sell_price", "YYYP_sell_price", "BUFF_buy_price", "YYYP_buy_price",
                                     "BUFF_sell_num", "YYYP_sell_num", "BUFF_buy_num", "YYYP_buy_num"]:
                            item_data[field] = np.nan
                except Exception as e:
                    print(f"    ❌ 获取batch_price失败: {e}")
                    # 设置默认值
                    for field in ["BUFF_sell_price", "YYYP_sell_price", "BUFF_buy_price", "YYYP_buy_price",
                                 "BUFF_sell_num", "YYYP_sell_num", "BUFF_buy_num", "YYYP_buy_num"]:
                        item_data[field] = np.nan
            else:
                print(f"    ❌ 无法获取market_hash_name")
                # 设置默认值
                for field in ["BUFF_sell_price", "YYYP_sell_price", "BUFF_buy_price", "YYYP_buy_price",
                             "BUFF_sell_num", "YYYP_sell_num", "BUFF_buy_num", "YYYP_buy_num"]:
                    item_data[field] = np.nan
            
            # 成交量信息
            item_data["BUFF_statistic"] = vol_data.get(str(good_id), 0)
            item_data["YYYP_statistic"] = vol_data.get(str(good_id), 0)  # 暂时使用相同值
            
            # 打印调试信息
            print(f"    商品ID: {good_id}")
            print(f"    商品名称: {item_data['name']}")
            print(f"    BUFF售价: {item_data.get('BUFF_sell_price', 'N/A')}")
            print(f"    YYYP售价: {item_data.get('YYYP_sell_price', 'N/A')}")
            print(f"    BUFF求购: {item_data.get('BUFF_buy_price', 'N/A')}")
            print(f"    YYYP求购: {item_data.get('YYYP_buy_price', 'N/A')}")
            print(f"    BUFF在售: {item_data.get('BUFF_sell_num', 'N/A')}")
            print(f"    YYYP在售: {item_data.get('YYYP_sell_num', 'N/A')}")
            print(f"    BUFF求购数: {item_data.get('BUFF_buy_num', 'N/A')}")
            print(f"    YYYP求购数: {item_data.get('YYYP_buy_num', 'N/A')}")
            
            return item_data
            
        except Exception as e:
            print(f"    获取商品 {good_id} 当前数据失败：{e}")
            return {
                "time": self.get_beijing_time(),
                "good_id": str(good_id),
                "name": f"Unknown {good_id}",
                "market_hash_name": "",
                "exterior": "",
                "collection": "",
                "BUFF_sell_price": np.nan,
                "YYYP_sell_price": np.nan,
                "BUFF_buy_price": np.nan,
                "YYYP_buy_price": np.nan,
                "BUFF_sell_num": np.nan,
                "YYYP_sell_num": np.nan,
                "BUFF_buy_num": np.nan,
                "YYYP_buy_num": np.nan,
                "BUFF_statistic": vol_data.get(str(good_id), 0),
                "YYYP_statistic": vol_data.get(str(good_id), 0)
            }
    
    def get_skin_type(self, item_name: str, exterior: str, collection: str) -> str:
        """根据物品名称、外观和收藏品确定皮肤类型"""
        # 提取皮肤类型
        if "多普勒" in item_name or "doppler" in item_name.lower():
            if "红宝石" in item_name or "ruby" in item_name.lower():
                return "红宝石"
            elif "蓝宝石" in item_name or "sapphire" in item_name.lower():
                return "蓝宝石"
            elif "绿宝石" in item_name or "emerald" in item_name.lower():
                return "绿宝石"
            elif "phase" in item_name.lower():
                # 提取Phase信息
                if "phase 1" in item_name.lower() or "p1" in item_name.lower():
                    return "Phase1"
                elif "phase 2" in item_name.lower() or "p2" in item_name.lower():
                    return "Phase2"
                elif "phase 3" in item_name.lower() or "p3" in item_name.lower():
                    return "Phase3"
                elif "phase 4" in item_name.lower() or "p4" in item_name.lower():
                    return "Phase4"
                else:
                    return "多普勒"
            else:
                return "多普勒"
        
        # 其他皮肤类型
        skin_keywords = [
            "蓝钢", "blue steel", "北方森林", "boreal forest", "都市危机", "urban masked",
            "深红之网", "crimson web", "致命紫罗兰", "fade", "渐变", "fade",
            "虎牙", "tiger tooth", "大理石", "marble fade", "多普勒", "doppler",
            "伽马多普勒", "gamma doppler", "自动", "autotronic", "黑色层压板", "black laminate",
            "自由之手", "freehand", "屠夫", "slaughter", "噩梦", "nightmare",
            "血网", "blood web", "血网", "blood web", "血网", "blood web"
        ]
        
        item_name_lower = item_name.lower()
        for i in range(0, len(skin_keywords), 2):
            chinese = skin_keywords[i]
            english = skin_keywords[i + 1]
            if chinese in item_name or english in item_name_lower:
                return chinese
        
        # 如果没有匹配到特定皮肤，使用外观
        if exterior:
            return exterior
        else:
            return "默认"
    
    def save_item_data(self, item_type: str, item_data: Dict[str, Any]):
        """保存单个商品数据到指定目录结构"""
        try:
            # 获取物品类型所属的类别
            category = self.get_category_for_item_type(item_type)
            
            # 创建目录结构：dataset/类别/物品类型/
            item_dir = os.path.join(self.dataset_dir, category, item_type)
            self.ensure_dir(item_dir)
            
            # 文件名：使用商品ID和名称，确保每个商品独立
            good_id = item_data.get("good_id", "")
            item_name = item_data.get("name", "")
            
            # 清理文件名
            safe_name = self.sanitize_filename(item_name)
            csv_file = os.path.join(item_dir, f"{good_id}_{safe_name}.csv")
            
            # 准备数据行
            data_row = {
                "data": item_data["time"],
                "BUFF_sell_price": item_data.get("BUFF_sell_price", np.nan),
                "YYYP_sell_price": item_data.get("YYYP_sell_price", np.nan),
                "BUFF_buy_price": item_data.get("BUFF_buy_price", np.nan),
                "YYYP_buy_price": item_data.get("YYYP_buy_price", np.nan),
                "BUFF_sell_num": item_data.get("BUFF_sell_num", np.nan),
                "YYYP_sell_num": item_data.get("YYYP_sell_num", np.nan),
                "BUFF_buy_num": item_data.get("BUFF_buy_num", np.nan),
                "YYYP_buy_num": item_data.get("YYYP_buy_num", np.nan),
                "YYYP_lease_num": item_data.get("YYYP_lease_num", np.nan),
                "YYYP_transfer_price": item_data.get("YYYP_transfer_price", np.nan),
                "YYYP_lease_price": item_data.get("YYYP_lease_price", np.nan),
                "YYYP_long_lease_price": item_data.get("YYYP_long_lease_price", np.nan),
                "YYYP_lease_annual": item_data.get("YYYP_lease_annual", np.nan),
                "YYYP_long_lease_annual": item_data.get("YYYP_long_lease_annual", np.nan),
                "BUFF_statistic": item_data.get("BUFF_statistic", 0),
                "YYYP_statistic": item_data.get("YYYP_statistic", 0),
                "good_id": item_data["good_id"]
            }
            
            # 检查文件是否存在
            if os.path.exists(csv_file):
                # 文件存在，追加数据
                df = pd.DataFrame([data_row])
                df.to_csv(csv_file, mode='a', header=False, index=False, encoding='utf-8')
                print(f"    📝 追加数据到：{os.path.abspath(csv_file)}")
            else:
                # 文件不存在，创建新文件
                df = pd.DataFrame([data_row])
                df.to_csv(csv_file, index=False, encoding='utf-8')
                print(f"    📄 创建新文件：{os.path.abspath(csv_file)}")
            
            return csv_file
                
        except Exception as e:
            print(f"    ❌ 保存数据失败：{e}")
            return None
    
    def save_item_data_thread_safe(self, item_type: str, item_data: Dict[str, Any]) -> str:
        """线程安全的保存单个商品数据"""
        try:
            # 获取物品类型所属的类别
            category = self.get_category_for_item_type(item_type)
            
            # 创建目录结构：dataset/类别/物品类型/
            item_dir = os.path.join(self.dataset_dir, category, item_type)
            os.makedirs(item_dir, exist_ok=True)
            
            # 文件名
            good_id = item_data.get("good_id", "")
            item_name = item_data.get("name", "")
            safe_name = self.sanitize_filename(item_name)
            csv_file = os.path.join(item_dir, f"{good_id}_{safe_name}.csv")
            
            # 获取文件锁
            if csv_file not in self.file_locks:
                with self.lock:
                    if csv_file not in self.file_locks:
                        self.file_locks[csv_file] = threading.Lock()
            
            file_lock = self.file_locks[csv_file]
            
            with file_lock:
                # 准备数据行
                data_row = {
                    "data": item_data["time"],
                    "BUFF_sell_price": item_data.get("BUFF_sell_price", np.nan),
                    "YYYP_sell_price": item_data.get("YYYP_sell_price", np.nan),
                    "BUFF_buy_price": item_data.get("BUFF_buy_price", np.nan),
                    "YYYP_buy_price": item_data.get("YYYP_buy_price", np.nan),
                    "BUFF_sell_num": item_data.get("BUFF_sell_num", np.nan),
                    "YYYP_sell_num": item_data.get("YYYP_sell_num", np.nan),
                    "BUFF_buy_num": item_data.get("BUFF_buy_num", np.nan),
                    "YYYP_buy_num": item_data.get("YYYP_buy_num", np.nan),
                    "YYYP_lease_num": item_data.get("YYYP_lease_num", np.nan),
                    "YYYP_transfer_price": item_data.get("YYYP_transfer_price", np.nan),
                    "YYYP_lease_price": item_data.get("YYYP_lease_price", np.nan),
                    "YYYP_long_lease_price": item_data.get("YYYP_long_lease_price", np.nan),
                    "YYYP_lease_annual": item_data.get("YYYP_lease_annual", np.nan),
                    "YYYP_long_lease_annual": item_data.get("YYYP_long_lease_annual", np.nan),
                    "BUFF_statistic": item_data.get("BUFF_statistic", 0),
                    "YYYP_statistic": item_data.get("YYYP_statistic", 0),
                    "good_id": item_data["good_id"]
                }
                
                # 保存数据
                if os.path.exists(csv_file):
                    df = pd.DataFrame([data_row])
                    df.to_csv(csv_file, mode='a', header=False, index=False, encoding='utf-8')
                else:
                    df = pd.DataFrame([data_row])
                    df.to_csv(csv_file, index=False, encoding='utf-8')
            
            return csv_file
            
        except Exception as e:
            print(f"❌ 保存商品 {item_data['good_id']} 数据失败：{e}")
            return None
    
    def process_good_detail(self, good_id: str, detail: Dict[str, Any], cached_info: Dict[str, Any], vol_data: Dict[str, int], item_type: str) -> List[Dict[str, Any]]:
        """处理单个商品详情数据（多线程安全）"""
        try:
            goods_info = detail.get("data", {}).get("goods_info", {})
            dpl_list = detail.get("data", {}).get("dpl", [])
            
            # 构建基础数据
            item_data = {
                "time": self.get_beijing_time(),
                "good_id": str(good_id),
                "name": cached_info.get("name", ""),
                "market_hash_name": cached_info.get("market_hash_name", ""),
                "exterior": "",
                "collection": ""
            }
            
            # 检查是否为多普勒系列商品
            if dpl_list and len(dpl_list) > 0:
                # 处理多普勒变体
                all_items_data = []
                for dpl_item in dpl_list:
                    doppler_item_data = item_data.copy()
                    
                    # 更新商品信息
                    doppler_item_data["good_id"] = f"{good_id}_{dpl_item.get('key', 'unknown')}"
                    doppler_item_data["name"] = f"{item_data['name']} | {dpl_item.get('label', 'Unknown')}"
                    doppler_item_data["exterior"] = goods_info.get("exterior_localized_name", "")
                    doppler_item_data["collection"] = goods_info.get("group_hash_name", "")
                    
                    # 使用多普勒变体的价格数据
                    doppler_item_data["BUFF_sell_price"] = dpl_item.get("buff_sell_price", np.nan)
                    doppler_item_data["BUFF_buy_price"] = dpl_item.get("buff_buy_price", np.nan)
                    
                    # 其他数据使用基础商品的信息
                    doppler_item_data["YYYP_sell_price"] = goods_info.get("yyyp_sell_price", np.nan)
                    doppler_item_data["YYYP_buy_price"] = goods_info.get("yyyp_buy_price", np.nan)
                    doppler_item_data["BUFF_sell_num"] = goods_info.get("buff_sell_num", np.nan)
                    doppler_item_data["YYYP_sell_num"] = goods_info.get("yyyp_sell_num", np.nan)
                    doppler_item_data["BUFF_buy_num"] = goods_info.get("buff_buy_num", np.nan)
                    doppler_item_data["YYYP_buy_num"] = goods_info.get("yyyp_buy_num", np.nan)
                    
                    # 获取YYYP租赁相关信息
                    doppler_item_data["YYYP_lease_num"] = goods_info.get("yyyp_lease_num", np.nan)
                    doppler_item_data["YYYP_transfer_price"] = goods_info.get("yyyp_transfer_price", np.nan)
                    doppler_item_data["YYYP_lease_price"] = goods_info.get("yyyp_lease_price", np.nan)
                    doppler_item_data["YYYP_long_lease_price"] = goods_info.get("yyyp_long_lease_price", np.nan)
                    doppler_item_data["YYYP_lease_annual"] = goods_info.get("yyyp_lease_annual", np.nan)
                    doppler_item_data["YYYP_long_lease_annual"] = goods_info.get("yyyp_long_lease_annual", np.nan)
                    
                    # 成交量信息
                    doppler_item_data["BUFF_statistic"] = vol_data.get(str(good_id), 0)
                    doppler_item_data["YYYP_statistic"] = vol_data.get(str(good_id), 0)
                    
                    all_items_data.append(doppler_item_data)
                
                return all_items_data
            else:
                # 处理普通商品
                item_data["BUFF_sell_price"] = goods_info.get("buff_sell_price", np.nan)
                item_data["YYYP_sell_price"] = goods_info.get("yyyp_sell_price", np.nan)
                item_data["BUFF_buy_price"] = goods_info.get("buff_buy_price", np.nan)
                item_data["YYYP_buy_price"] = goods_info.get("yyyp_buy_price", np.nan)
                item_data["BUFF_sell_num"] = goods_info.get("buff_sell_num", np.nan)
                item_data["YYYP_sell_num"] = goods_info.get("yyyp_sell_num", np.nan)
                item_data["BUFF_buy_num"] = goods_info.get("buff_buy_num", np.nan)
                item_data["YYYP_buy_num"] = goods_info.get("yyyp_buy_num", np.nan)
                
                # 获取YYYP租赁相关信息
                item_data["YYYP_lease_num"] = goods_info.get("yyyp_lease_num", np.nan)
                item_data["YYYP_transfer_price"] = goods_info.get("yyyp_transfer_price", np.nan)
                item_data["YYYP_lease_price"] = goods_info.get("yyyp_lease_price", np.nan)
                item_data["YYYP_long_lease_price"] = goods_info.get("yyyp_long_lease_price", np.nan)
                item_data["YYYP_lease_annual"] = goods_info.get("yyyp_lease_annual", np.nan)
                item_data["YYYP_long_lease_annual"] = goods_info.get("yyyp_long_lease_annual", np.nan)
                
                # 获取其他有用信息
                item_data["exterior"] = goods_info.get("exterior_localized_name", "")
                item_data["collection"] = goods_info.get("group_hash_name", "")
                
                # 成交量信息
                item_data["BUFF_statistic"] = vol_data.get(str(good_id), 0)
                item_data["YYYP_statistic"] = vol_data.get(str(good_id), 0)
                
                return [item_data]
                
        except Exception as e:
            print(f"❌ 处理商品 {good_id} 数据失败：{e}")
            return []
    
    def process_good_worker(self, args):
        """工作线程函数：处理单个商品"""
        good_id, cached_info, vol_data, item_type = args
        
        try:
            # 获取商品详情
            detail = self.get_single_good_detail(good_id)
            if not detail:
                return []
            
            # 处理商品数据
            items_data = self.process_good_detail(good_id, detail, cached_info, vol_data, item_type)
            
            # 实时保存数据
            saved_files = []
            for item_data in items_data:
                saved_file = self.save_item_data_thread_safe(item_type, item_data)
                if saved_file:
                    saved_files.append(saved_file)
            
            return saved_files
                
        except Exception as e:
            print(f"❌ 处理商品 {good_id} 失败：{e}")
            return []
    
    def check_total_items_count(self, item_type: str, all_items_info: Dict[str, Any]) -> bool:
        """检查模板筛选后的物品数量是否超过限制"""
        total_count = len(all_items_info)
        MAX_ITEMS_LIMIT = 1800
        
        print(f"📊 模板筛选后物品数量检查：")
        print(f"  - {item_type} 筛选后物品数量：{total_count}")
        print(f"  - 限制数量：{MAX_ITEMS_LIMIT}")
        
        if total_count > MAX_ITEMS_LIMIT:
            print(f"❌ 物品数量超过限制！")
            print(f"  - 当前数量：{total_count}")
            print(f"  - 限制数量：{MAX_ITEMS_LIMIT}")
            print(f"  - 超出数量：{total_count - MAX_ITEMS_LIMIT}")
            print(f"🛑 停止构建数据集")
            return False
        else:
            print(f"✅ 物品数量在限制范围内")
            return True
    
    def check_global_items_count(self, item_types: List[str]) -> bool:
        """检查全局物品数量是否超过限制（真实模板筛选后）"""
        MAX_ITEMS_LIMIT = 1800
        total_filtered_count = 0
        filtered_count_by_type = {}
        
        print(f"🌍 全局物品数量检查（真实模板筛选后）：")
        
        for item_type in item_types:
            # 获取物品类型的关键词
            all_types = self.get_all_item_types()
            if item_type not in all_types:
                continue
            
            # 尝试从缓存加载商品信息
            cache_data = self.load_cached_items(item_type)
            if cache_data and 'items' in cache_data:
                all_items_info = cache_data['items']
                
                # 真实进行模板筛选（静默模式）
                filtered_items_info = self.filter_items_by_templates(item_type, all_items_info, verbose=False)
                filtered_count = len(filtered_items_info)
                
                total_filtered_count += filtered_count
                filtered_count_by_type[item_type] = filtered_count
                print(f"  - {item_type}: {len(all_items_info)} 个 → 筛选后 {filtered_count} 个")
        
        print(f"  - 总计筛选后物品数量：{total_filtered_count}")
        print(f"  - 限制数量：{MAX_ITEMS_LIMIT}")
        
        if total_filtered_count > MAX_ITEMS_LIMIT:
            print(f"❌ 全局筛选后物品数量超过限制！")
            print(f"  - 当前总数：{total_filtered_count}")
            print(f"  - 限制数量：{MAX_ITEMS_LIMIT}")
            print(f"  - 超出数量：{total_filtered_count - MAX_ITEMS_LIMIT}")
            print(f"🛑 停止构建数据集")
            return False
        else:
            print(f"✅ 全局筛选后物品数量在限制范围内")
            return True
    
    def sanitize_filename(self, filename: str) -> str:
        """清理文件名"""
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = re.sub(r'\s+', ' ', filename).strip()
        filename = filename.replace('.', '_')
        filename = re.sub(r'[()（）★™]', '', filename)
        filename = re.sub(r'[|]', '_', filename)
        if len(filename) > 80:
            filename = filename[:80]
        if not filename.strip():
            filename = "Unknown_Item"
        return filename.strip()
    
    def build_item_database(self, item_type: str, keywords: List[str], test_mode: bool = False, max_items: int = None) -> List[str]:
        """构建指定物品类型的实时数据库"""
        start_time = time.time()
        category_name = self.get_category_for_item_type(item_type)
        print(f"🚀 开始记录 {category_name} - {item_type} 实时数据...")
        print(f"⏰ 记录时间：{self.current_time}")
        
        if self.use_multithreading:
            print(f"⚙️ 多线程模式：{self.max_workers}个线程 + 实时写入")
        else:
            print(f"⚙️ 串行模式：单线程 + 批量写入")
        
        # 获取成交量数据
        print("📊 获取成交量数据...")
        vol_data = self.get_vol_data_info()
        print(f"✅ 成功获取 {len(vol_data)} 个物品的成交量数据")
        
        # 尝试从缓存加载商品信息
        refresh_cache = getattr(self, 'refresh_cache', False)
        use_cache = getattr(self, 'use_cache', False)
        
        if use_cache:
            # 强制使用缓存模式
            cache_data = self.load_cached_items(item_type)
            if cache_data and 'items' in cache_data:
                all_items_info = cache_data['items']
                print(f"✅ 强制使用缓存数据，跳过搜索阶段")
            else:
                print(f"❌ 缓存不存在，无法强制使用缓存模式")
                return []
        elif refresh_cache:
            print(f"🔄 刷新缓存模式，重新搜索 {item_type}...")
            all_items_info = self.search_and_cache_items(item_type, keywords)
        else:
            cache_data = self.load_cached_items(item_type)
            if cache_data and 'items' in cache_data:
                all_items_info = cache_data['items']
                print(f"✅ 使用缓存数据，跳过搜索阶段")
            else:
                # 如果没有缓存，搜索并缓存商品信息
                print(f"🔍 首次搜索 {item_type}，正在建立缓存...")
                all_items_info = self.search_and_cache_items(item_type, keywords)
        
        if not all_items_info:
            print(f"❌ 未找到 {item_type} 的商品")
            return []
        
        # 根据测试模式和限制数量处理商品列表
        good_ids = list(all_items_info.keys())
        if test_mode and max_items:
            if len(good_ids) > max_items:
                import random
                # 优先选择多普勒商品进行测试（仅对匕首类别）
                if category_name == "匕首":
                    doppler_good_ids = []
                    regular_good_ids = []
                    
                    for good_id in good_ids:
                        item_name = all_items_info[good_id].get("name", "")
                        if "多普勒" in item_name or "伽玛多普勒" in item_name:
                            doppler_good_ids.append(good_id)
                        else:
                            regular_good_ids.append(good_id)
                    
                    # 如果有多普勒商品，优先选择
                    if doppler_good_ids:
                        selected_count = min(max_items, len(doppler_good_ids))
                        good_ids = random.sample(doppler_good_ids, selected_count)
                        print(f"🎲 测试模式：优先选择 {len(good_ids)} 个多普勒商品")
                    else:
                        good_ids = random.sample(good_ids, max_items)
                        print(f"🎲 测试模式：随机选择 {len(good_ids)} 个商品")
                else:
                    good_ids = random.sample(good_ids, max_items)
                    print(f"🎲 测试模式：随机选择 {len(good_ids)} 个商品")
        elif max_items and len(good_ids) > max_items:
            good_ids = good_ids[:max_items]
            print(f"📝 限制数量：选择前 {len(good_ids)} 个商品")
        
        print(f"✅ {item_type} 准备处理 {len(good_ids)} 个商品")
        
        # 根据模版配置筛选商品（对所有类别都生效）
        filtered_items_info = self.filter_items_by_templates(item_type, all_items_info)
        filtered_good_ids = list(filtered_items_info.keys())
        
        if len(filtered_good_ids) == 0:
            print(f"❌ {item_type} 模版筛选后没有符合条件的商品")
            return []
        
        # 检查模板筛选后的物品数量是否超过限制
        if not self.check_total_items_count(item_type, filtered_items_info):
            return []
        
        print(f"🎯 {item_type} 最终处理 {len(filtered_good_ids)} 个商品")
        
        if self.use_multithreading:
            # 多线程处理模式
            return self._build_item_database_multithread(item_type, filtered_good_ids, filtered_items_info, vol_data)
        else:
            # 串行处理模式（原有逻辑）
            return self._build_item_database_serial(item_type, filtered_good_ids, filtered_items_info, vol_data)
    
    def _build_item_database_multithread(self, item_type: str, good_ids: List[str], all_items_info: Dict[str, Any], vol_data: Dict[str, int]) -> List[str]:
        """多线程模式构建数据库"""
        start_time = time.time()  # 添加start_time定义
        print(f"🚀 使用多线程模式处理 {len(good_ids)} 个商品...")
        
        # 准备任务参数
        tasks = []
        for good_id in good_ids:
            if good_id in all_items_info:
                cached_info = all_items_info[good_id]
                tasks.append((good_id, cached_info, vol_data, item_type))
        
        print(f"📊 准备处理 {len(tasks)} 个商品...")
        
        # 使用线程池处理
        all_saved_files = []
        completed_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_good_id = {executor.submit(self.process_good_worker, task): task[0] for task in tasks}
            
            # 处理完成的任务
            for future in as_completed(future_to_good_id):
                good_id = future_to_good_id[future]
                try:
                    saved_files = future.result()
                    all_saved_files.extend(saved_files)
                    completed_count += 1
                    
                    # 显示进度
                    if completed_count % 10 == 0 or completed_count == len(tasks):
                        progress = (completed_count / len(tasks)) * 100
                        print(f"📈 进度：{completed_count}/{len(tasks)} ({progress:.1f}%) - 已保存 {len(all_saved_files)} 个文件")
                        
                except Exception as e:
                    print(f"❌ 处理商品 {good_id} 时发生异常：{e}")
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"✅ {item_type} 多线程处理完成")
        print(f"  - 处理商品：{completed_count} 个")
        print(f"  - 保存文件：{len(all_saved_files)} 个")
        print(f"  - 耗时：{duration:.2f} 秒")
        print(f"  - 平均耗时：{duration/len(tasks):.2f} 秒/商品")
        print(f"  - API请求：{self.stats['successful_requests']}/{self.stats['total_requests']} 成功")
        print(f"  - 限流次数：{self.stats['rate_limit_hits']}")
        
        return all_saved_files
    
    def _build_item_database_serial(self, item_type: str, good_ids: List[str], all_items_info: Dict[str, Any], vol_data: Dict[str, int]) -> List[str]:
        """串行模式构建数据库（原有逻辑）"""
        start_time = time.time()  # 添加start_time定义
        print(f"🚀 使用串行模式处理 {len(good_ids)} 个商品...")
        
        # 第一步：提取所有market_hash_name（从缓存中获取，避免重复API调用）
        print("📡 准备批量价格查询...")
        market_hash_names = []
        good_id_to_mhn = {}
        
        for good_id in good_ids:
            if good_id in all_items_info:
                mhn = all_items_info[good_id].get("market_hash_name")
                if mhn:
                    market_hash_names.append(mhn)
                    good_id_to_mhn[good_id] = mhn
        
        print(f"✅ 从缓存提取到 {len(market_hash_names)} 个有效的market_hash_name")
        
        # 第二步：获取所有商品详细信息（API合规版本）
        print("📊 获取商品详细信息（API合规模式）...")
        
        # 使用API合规的商品详情获取
        good_details = self.get_all_good_details(good_ids)
        
        # 处理商品详情数据
        all_items_data = []
        
        for good_id, detail in good_details.items():
            if good_id not in all_items_info:
                continue
            
            cached_info = all_items_info[good_id]
            
            # 构建基础数据
            item_data = {
                "time": self.get_beijing_time(),
                "good_id": str(good_id),
                "name": cached_info.get("name", ""),
                "market_hash_name": cached_info.get("market_hash_name", ""),
                "exterior": "",
                "collection": ""
            }
            
            try:
                goods_info = detail.get("data", {}).get("goods_info", {})
                dpl_list = detail.get("data", {}).get("dpl", [])
                
                # 检查是否为多普勒系列商品
                if dpl_list and len(dpl_list) > 0:
                    # 这是多普勒系列商品，需要为每个变体创建独立的数据
                    print(f"    🔍 发现多普勒系列商品，包含 {len(dpl_list)} 个变体")
                    
                    # 为每个多普勒变体创建独立的数据项
                    for dpl_item in dpl_list:
                        # 创建新的数据项
                        doppler_item_data = item_data.copy()
                        
                        # 更新商品信息
                        doppler_item_data["good_id"] = f"{good_id}_{dpl_item.get('key', 'unknown')}"
                        doppler_item_data["name"] = f"{item_data['name']} | {dpl_item.get('label', 'Unknown')}"
                        doppler_item_data["exterior"] = goods_info.get("exterior_localized_name", "")
                        doppler_item_data["collection"] = goods_info.get("group_hash_name", "")
                        
                        # 使用多普勒变体的价格数据
                        doppler_item_data["BUFF_sell_price"] = dpl_item.get("buff_sell_price", np.nan)
                        doppler_item_data["BUFF_buy_price"] = dpl_item.get("buff_buy_price", np.nan)
                        
                        # 其他数据使用基础商品的信息
                        doppler_item_data["YYYP_sell_price"] = goods_info.get("yyyp_sell_price", np.nan)
                        doppler_item_data["YYYP_buy_price"] = goods_info.get("yyyp_buy_price", np.nan)
                        doppler_item_data["BUFF_sell_num"] = goods_info.get("buff_sell_num", np.nan)
                        doppler_item_data["YYYP_sell_num"] = goods_info.get("yyyp_sell_num", np.nan)
                        doppler_item_data["BUFF_buy_num"] = goods_info.get("buff_buy_num", np.nan)
                        doppler_item_data["YYYP_buy_num"] = goods_info.get("yyyp_buy_num", np.nan)
                        
                        # 获取YYYP租赁相关信息
                        doppler_item_data["YYYP_lease_num"] = goods_info.get("yyyp_lease_num", np.nan)
                        doppler_item_data["YYYP_transfer_price"] = goods_info.get("yyyp_transfer_price", np.nan)
                        doppler_item_data["YYYP_lease_price"] = goods_info.get("yyyp_lease_price", np.nan)
                        doppler_item_data["YYYP_long_lease_price"] = goods_info.get("yyyp_long_lease_price", np.nan)
                        doppler_item_data["YYYP_lease_annual"] = goods_info.get("yyyp_lease_annual", np.nan)
                        doppler_item_data["YYYP_long_lease_annual"] = goods_info.get("yyyp_long_lease_annual", np.nan)
                        
                        # 成交量信息
                        doppler_item_data["BUFF_statistic"] = vol_data.get(str(good_id), 0)
                        doppler_item_data["YYYP_statistic"] = vol_data.get(str(good_id), 0)
                        
                        all_items_data.append(doppler_item_data)
                        
                        # 打印调试信息（仅显示前几个）
                        if len(all_items_data) <= 6:  # 增加显示数量，因为多普勒商品会生成多个变体
                            print(f"    📊 多普勒变体 {dpl_item.get('label', 'Unknown')}: {doppler_item_data['name']}")
                            print(f"      BUFF售价: {doppler_item_data.get('BUFF_sell_price', 'N/A')}")
                            print(f"      BUFF求购: {doppler_item_data.get('BUFF_buy_price', 'N/A')}")
                            print(f"      YYYP售价: {doppler_item_data.get('YYYP_sell_price', 'N/A')}")
                            print(f"      YYYP求购: {doppler_item_data.get('YYYP_buy_price', 'N/A')}")
                    
                    # 跳过原始商品的处理，因为已经为每个变体创建了独立数据
                    continue
                    
                else:
                    # 普通商品，使用原有逻辑
                    # 从详细信息中获取价格和数量数据
                    item_data["BUFF_sell_price"] = goods_info.get("buff_sell_price", np.nan)
                    item_data["YYYP_sell_price"] = goods_info.get("yyyp_sell_price", np.nan)
                    item_data["BUFF_buy_price"] = goods_info.get("buff_buy_price", np.nan)
                    item_data["YYYP_buy_price"] = goods_info.get("yyyp_buy_price", np.nan)
                    item_data["BUFF_sell_num"] = goods_info.get("buff_sell_num", np.nan)
                    item_data["YYYP_sell_num"] = goods_info.get("yyyp_sell_num", np.nan)
                    item_data["BUFF_buy_num"] = goods_info.get("buff_buy_num", np.nan)
                    item_data["YYYP_buy_num"] = goods_info.get("yyyp_buy_num", np.nan)
                    
                    # 获取YYYP租赁相关信息
                    item_data["YYYP_lease_num"] = goods_info.get("yyyp_lease_num", np.nan)
                    item_data["YYYP_transfer_price"] = goods_info.get("yyyp_transfer_price", np.nan)
                    item_data["YYYP_lease_price"] = goods_info.get("yyyp_lease_price", np.nan)
                    item_data["YYYP_long_lease_price"] = goods_info.get("yyyp_long_lease_price", np.nan)
                    item_data["YYYP_lease_annual"] = goods_info.get("yyyp_lease_annual", np.nan)
                    item_data["YYYP_long_lease_annual"] = goods_info.get("yyyp_long_lease_annual", np.nan)
                    
                    # 获取其他有用信息
                    item_data["exterior"] = goods_info.get("exterior_localized_name", "")
                    item_data["collection"] = goods_info.get("group_hash_name", "")
                    
                    # 成交量信息
                    item_data["BUFF_statistic"] = vol_data.get(str(good_id), 0)
                    item_data["YYYP_statistic"] = vol_data.get(str(good_id), 0)
                    
                    all_items_data.append(item_data)
                    
                    # 打印调试信息（仅显示前几个）
                    if len(all_items_data) <= 3:
                        print(f"    📊 商品 {good_id}: {item_data['name']}")
                        print(f"      BUFF售价: {item_data.get('BUFF_sell_price', 'N/A')}")
                        print(f"      YYYP售价: {item_data.get('YYYP_sell_price', 'N/A')}")
                        print(f"      BUFF求购: {item_data.get('BUFF_buy_price', 'N/A')}")
                        print(f"      YYYP求购: {item_data.get('YYYP_buy_price', 'N/A')}")
                        print(f"      BUFF在售: {item_data.get('BUFF_sell_num', 'N/A')}")
                        print(f"      YYYP在售: {item_data.get('YYYP_sell_num', 'N/A')}")
                        print(f"      BUFF求购数: {item_data.get('BUFF_buy_num', 'N/A')}")
                        print(f"      YYYP求购数: {item_data.get('YYYP_buy_num', 'N/A')}")
                        print(f"      YYYP在租: {item_data.get('YYYP_lease_num', 'N/A')}")
                        print(f"      YYYP过户价: {item_data.get('YYYP_transfer_price', 'N/A')}")
                        print(f"      YYYP短租价: {item_data.get('YYYP_lease_price', 'N/A')}")
                        print(f"      YYYP长租价: {item_data.get('YYYP_long_lease_price', 'N/A')}")
                        print(f"      YYYP短租年化: {item_data.get('YYYP_lease_annual', 'N/A')}%")
                        print(f"      YYYP长租年化: {item_data.get('YYYP_long_lease_annual', 'N/A')}%")
                
            except Exception as e:
                print(f"    ❌ 处理商品 {good_id} 数据失败：{e}")
                # 设置默认值
                for field in ["BUFF_sell_price", "YYYP_sell_price", "BUFF_buy_price", "YYYP_buy_price",
                             "BUFF_sell_num", "YYYP_sell_num", "BUFF_buy_num", "YYYP_buy_num",
                             "YYYP_lease_num", "YYYP_transfer_price", "YYYP_lease_price", 
                             "YYYP_long_lease_price", "YYYP_lease_annual", "YYYP_long_lease_annual"]:
                    item_data[field] = np.nan
                
                # 成交量信息
                item_data["BUFF_statistic"] = vol_data.get(str(good_id), 0)
                item_data["YYYP_statistic"] = vol_data.get(str(good_id), 0)
                
                all_items_data.append(item_data)
        
        print(f"✅ 成功获取 {len(all_items_data)} 个商品的完整数据")
        
        # 第四步：保存数据
        print("💾 保存数据到文件...")
        saved_files = []
        for item_data in all_items_data:
            try:
                saved_file = self.save_item_data(item_type, item_data)
                if saved_file:
                    saved_files.append(saved_file)
            except Exception as e:
                print(f"❌ 保存商品 {item_data['good_id']} 数据失败：{e}")
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"✅ {item_type} 数据记录完成")
        print(f"  - 处理商品：{len(all_items_data)} 个")
        print(f"  - 保存文件：{len(saved_files)} 个")
        print(f"  - 耗时：{duration:.2f} 秒")
        print(f"  - API请求：{self.stats['successful_requests']}/{self.stats['total_requests']} 成功")
        print(f"  - 限流次数：{self.stats['rate_limit_hits']}")
        
        return saved_files
    
    def run(self, item_types: List[str] = None, test_mode: bool = False, max_items: int = None, category: str = None):
        """运行实时数据记录流程"""
        if category:
            # 如果指定了类别，只处理该类别下的物品类型
            item_types = list(ITEM_CATEGORIES.get(category, {}).keys())
            if not item_types:
                print(f"❌ 未找到类别：{category}")
                return {}
        elif item_types is None:
            # 如果没有指定类别和物品类型，处理所有物品类型
            item_types = []
            for cat_items in ITEM_CATEGORIES.values():
                item_types.extend(list(cat_items.keys()))
        
        print(f"🚀 开始记录 {len(item_types)} 种物品类型实时数据...")
        print(f"⏰ 记录时间：{self.current_time}")
        if test_mode:
            print(f"🧪 测试模式：每个物品类型随机选择1个物品")
        
        # 检查全局物品数量是否超过限制
        if not self.check_global_items_count(item_types):
            return {}
        
        # 确保主目录存在
        self.ensure_dir(self.dataset_dir)
        
        results = {}
        
        for item_type in item_types:
            # 获取物品类型的关键词
            all_types = self.get_all_item_types()
            if item_type not in all_types:
                print(f"⚠️ 未知物品类型：{item_type}")
                continue
            
            keywords = all_types[item_type]
            category_name = self.get_category_for_item_type(item_type)
            
            try:
                # 记录数据
                saved_files = self.build_item_database(item_type, keywords, test_mode=test_mode, max_items=max_items)
                    
                results[item_type] = {
                    'saved_files': len(saved_files) if saved_files else 0,
                    'success': True,
                    'category': category_name
                }
                
            except Exception as e:
                print(f"❌ {item_type} 记录失败：{e}")
                results[item_type] = {'success': False, 'error': str(e), 'category': category_name}
            
            print(f"\n{'='*50}")
        
        # 打印总结
        total_time = time.time() - self.stats['start_time']
        success_count = sum(1 for r in results.values() if r.get('success', False))
        
        print("\n📊 记录总结：")
        print(f"  - 成功记录：{success_count}/{len(item_types)} 种物品类型")
        print(f"  - 总耗时：{total_time:.2f} 秒")
        print(f"  - 平均耗时：{total_time/len(item_types):.2f} 秒/物品类型")
        print(f"  - API成功率：{self.stats['successful_requests']}/{self.stats['total_requests']} ({self.stats['successful_requests']/max(self.stats['total_requests'], 1)*100:.1f}%)")
        print(f"  - 限流次数：{self.stats['rate_limit_hits']}")
        print(f"  - 合规性：✅ 完全符合1次/秒API限制")
        if self.use_multithreading:
            print(f"  - 处理模式：🚀 多线程模式（{self.max_workers}线程 + 实时写入）")
        else:
            print(f"  - 处理模式：📝 串行模式（单线程 + 批量写入）")
        
        for item_type, result in results.items():
            if result.get('success', False):
                print(f"  ✅ {result.get('category', '未知')} - {item_type}: {result['saved_files']} 个文件")
            else:
                print(f"  ❌ {result.get('category', '未知')} - {item_type}: {result.get('error', 'Unknown error')}")
        
        return results
    
    def get_all_item_types(self, category: str = None) -> Dict[str, List[str]]:
        """获取所有物品类型"""
        if category:
            return ITEM_CATEGORIES.get(category, {})
        else:
            # 返回所有类别的所有物品类型
            all_types = {}
            for cat_name, cat_items in ITEM_CATEGORIES.items():
                all_types.update(cat_items)
            return all_types
    
    def get_category_for_item_type(self, item_type: str) -> str:
        """根据物品类型获取所属类别"""
        for category, items in ITEM_CATEGORIES.items():
            if item_type in items:
                return category
        return "未知类别"
    
    def is_valid_item_for_knife_type(self, item_name: str, knife_type: str) -> bool:
        """检查商品是否属于指定的刀型"""
        item_name_lower = item_name.lower()
        
        # 特殊处理M9刺刀
        if knife_type == "M9刺刀":
            # M9刺刀必须包含"M9"且包含"刺刀"
            return "m9" in item_name_lower and "刺刀" in item_name_lower
        
        # 特殊处理普通刺刀
        if knife_type == "刺刀":
            # 普通刺刀必须包含"刺刀"但不包含"M9"
            return "刺刀" in item_name_lower and "m9" not in item_name_lower
        
        # 其他刀型的处理
        # 获取排除关键词
        exclude_keywords = EXCLUDE_KEYWORDS.get(knife_type, [])
        
        # 检查是否包含排除关键词
        for exclude_keyword in exclude_keywords:
            if exclude_keyword.lower() in item_name_lower:
                return False
        
        # 检查是否包含目标刀型关键词
        target_keywords = KNIFE_KEYWORDS.get(knife_type, [])
        for keyword in target_keywords:
            if keyword.lower() in item_name_lower:
                return True
        
        return False
    
    def is_valid_item_for_type(self, item_name: str, item_type: str) -> bool:
        """检查商品是否属于指定的物品类型（通用版本）"""
        item_name_lower = item_name.lower()
        
        # 获取物品类型的关键词
        all_types = self.get_all_item_types()
        if item_type not in all_types:
            return False
        
        target_keywords = all_types[item_type]
        
        # 获取排除关键词
        exclude_keywords = EXCLUDE_KEYWORDS.get(item_type, [])
        
        # 检查是否包含排除关键词
        for exclude_keyword in exclude_keywords:
            if exclude_keyword.lower() in item_name_lower:
                return False
        
        # 特殊处理探员类别
        if item_type in ["T探员", "CT探员", "探员"]:
            # 探员类别不做关键词排除，直接检查是否包含目标关键词
            for keyword in target_keywords:
                if keyword.lower() in item_name_lower:
                    return True
            return False
        
        # 检查是否包含目标关键词
        for keyword in target_keywords:
            if keyword.lower() in item_name_lower:
                return True
        
        return False

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="实时记录物品数据（整合版本：支持匕首、探员、手枪、步枪、手套等类别）")
    parser.add_argument("--token", default=API_TOKEN, help="CSQAQ API Token")
    parser.add_argument("--items", nargs="+", help="指定要记录的物品类型（默认全部）")
    parser.add_argument("--category", choices=["匕首", "探员", "手枪", "步枪", "手套"], help="指定要处理的物品类别")
    parser.add_argument("--dataset-dir", default="./dataset", help="数据集目录")
    parser.add_argument("--test", action="store_true", help="测试模式：每个物品类型随机选择1个物品")
    parser.add_argument("--max-items", type=int, default=None, help="测试模式下搜索的最大物品数量（默认None表示处理所有商品）")
    parser.add_argument("--refresh-cache", action="store_true", help="刷新缓存，重新搜索所有商品")
    parser.add_argument("--use-cache", action="store_true", help="强制使用缓存，不进行搜索")
    parser.add_argument("--multithread", action="store_true", help="启用多线程处理")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help=f"多线程模式下最大工作线程数（默认{DEFAULT_MAX_WORKERS}）")
    parser.add_argument("--no-template-filter", action="store_true", help="禁用模版筛选，处理所有商品")
    
    args = parser.parse_args()
    
    if not args.token:
        raise SystemExit("需要提供API Token")
    
    # 记录数据
    builder = ItemDatabaseBuilder(
        args.token, 
        use_multithreading=args.multithread, 
        max_workers=args.max_workers,
        enable_template_filter=not args.no_template_filter
    )
    # 只有在用户明确指定dataset-dir参数时才覆盖默认设置
    if args.dataset_dir != "./dataset":  # 如果用户指定了自定义路径
        builder.dataset_dir = args.dataset_dir
    builder.refresh_cache = args.refresh_cache
    builder.use_cache = args.use_cache
    
    if args.category:
        # 处理指定类别
        item_types = None
        category = args.category
        print(f"🎯 处理类别：{category}")
    else:
        # 处理指定物品类型或全部
        item_types = args.items
        category = None
        if item_types:
            print(f"🎯 处理物品类型：{', '.join(item_types)}")
        else:
            print(f"🎯 处理所有物品类型")
    
    results = builder.run(item_types, test_mode=args.test, max_items=args.max_items, category=category)
    
    print(f"\n🎉 实时数据记录完成！")

if __name__ == "__main__":
    main()
