# -*- coding: utf-8 -*-
"""
build_cache.py

精确过滤版本：避免刀型之间的交叉匹配

修复问题：
- 刺刀缓存错误包含M9刺刀数据
- 搜索结果不够精确
- 需要更严格的名称匹配

目标：
- 独立获取所有刀型的物品缓存，不限时
- 为后续的快速数据库更新做准备
- 避免在定时任务中因超时而失败
- 精确过滤，避免刀型交叉匹配

使用方法：
python backend/Model/build_cache.py --token YOUR_API_TOKEN
"""

import os
import json
import sys
import time
from typing import Dict, List, Any
from datetime import datetime

# 导入CSQAQ客户端
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from CSQAQ import CsqaqClient
from config import API_TOKEN

# 需要过滤的关键词（在所有板块中都会被忽略）
FILTER_KEYWORDS = ["印花", "挂件", "音乐盒", "涂鸦"]

# 刀型关键词映射（从build_database.py复制）
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
    
    # 探员类别 - 直接使用所有探员名称作为关键词
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
        "USP 消音版": ["USP-S", "USP 消音版"],
        "格洛克 18 型": ["Glock-18", "格洛克 18 型", "Glock18"],
        "沙漠之鹰": ["Desert Eagle", "沙漠之鹰"],
    },
    
    # 步枪类别
    "步枪": {
        "AK-47": ["AK-47", "AK47"],
        "M4A1": ["M4A1", "M4A1-S"],
        "M4A4": ["M4A4"],
        "AWP": ["AWP"],
    },
    
    # 手套类别
    "手套": {
        "运动手套": ["运动手套", "Sport Gloves"],
        "专业手套": ["专业手套", "Professional Gloves"],
        "摩托手套": ["摩托手套", "Motorcycle Gloves"],
    },
}

# 排除关键词（避免交叉匹配）
EXCLUDE_KEYWORDS = {
    "刺刀": ["M9刺刀", "M9 刺刀"],  # 刺刀缓存排除M9刺刀
    "M9刺刀": [],  # M9刺刀缓存排除普通刺刀和自身（避免重复）
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

class CacheBuilder:
    def __init__(self, api_token: str):
        self.client = CsqaqClient(api_token=api_token)
        
        # 设置缓存目录
        base_dir = os.path.dirname(__file__)
        self.cache_dir = os.path.join(base_dir, "cache")
        
        # 确保缓存目录存在
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
    
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
    
    def should_filter_item(self, item_name: str, item_type: str) -> bool:
        """判断是否应该过滤掉某个物品（缓存版本：只过滤基础关键词）"""
        # 只过滤基础过滤关键词，不过滤StatTrak和外观品质
        if any(keyword in item_name for keyword in FILTER_KEYWORDS):
            return True
        return False
    
    def search_and_cache_items(self, knife_type: str, keywords: List[str]) -> Dict[str, Any]:
        """搜索并缓存商品信息（精确过滤版本）"""
        print(f"🔍 搜索 {knife_type} 商品（精确过滤）...")
        
        all_items_info = {}
        excluded_count = 0
        
        # 使用多个关键词搜索
        for keyword in keywords:
            print(f"  搜索关键词：{keyword}")
            
            # 分页获取所有商品
            page_index = 1
            while True:
                try:
                    print(f"    正在获取第 {page_index} 页...")
                    response = self.client.get_good_id(page_index=page_index, page_size=50, search=keyword)
                    data = response.get("data", {})
                    
                    # API返回的数据结构是 data.data，包含商品字典
                    goods_dict = data.get("data", {})
                    
                    if not goods_dict:
                        print(f"    第 {page_index} 页无数据，停止搜索")
                        break
                    
                    # 提取商品信息（精确过滤）
                    page_count = 0
                    page_excluded = 0
                    for good_id, item in goods_dict.items():
                        if good_id:
                            item_name = item.get("name", "")
                            
                            # 使用新的过滤函数
                            if self.should_filter_item(item_name, knife_type):
                                page_excluded += 1
                                excluded_count += 1
                                continue
                            
                            # 精确过滤：检查是否属于当前刀型
                            if self.is_valid_item_for_knife_type(item_name, knife_type):
                                all_items_info[str(good_id)] = {
                                    "good_id": str(good_id),
                                    "name": item_name,
                                    "market_hash_name": item.get("market_hash_name", ""),
                                    "keyword": keyword
                                }
                                page_count += 1
                            else:
                                page_excluded += 1
                                excluded_count += 1
                    
                    print(f"    第 {page_index} 页找到 {page_count} 个有效商品，排除 {page_excluded} 个")
                    
                    page_index += 1
                    
                    # 增加搜索页数限制，但给予更多时间
                    if page_index > 20:  # 增加到20页
                        print(f"    已达到最大页数限制（20页），停止搜索")
                        break
                    
                    # 添加延迟，避免API限制
                    time.sleep(1)
                        
                except Exception as e:
                    print(f"    获取第{page_index}页失败：{e}")
                    time.sleep(5)  # 失败后等待更长时间
                    break
        
        print(f"  总共找到 {len(all_items_info)} 个 {knife_type} 相关商品")
        print(f"  排除 {excluded_count} 个不相关商品")
        
        # 保存到缓存
        self.save_cached_items(knife_type, all_items_info)
        
        return all_items_info
    
    def search_and_cache_items_generic(self, item_type: str, keywords: List[str]) -> Dict[str, Any]:
        """搜索并缓存商品信息（通用版本，支持所有物品类型）"""
        print(f"🔍 搜索 {item_type} 商品（精确过滤）...")
        
        all_items_info = {}
        excluded_count = 0
        
        # 使用多个关键词搜索
        for keyword in keywords:
            print(f"  搜索关键词：{keyword}")
            
            # 分页获取所有商品
            page_index = 1
            while True:
                try:
                    print(f"    正在获取第 {page_index} 页...")
                    response = self.client.get_good_id(page_index=page_index, page_size=50, search=keyword)
                    data = response.get("data", {})
                    
                    # API返回的数据结构是 data.data，包含商品字典
                    goods_dict = data.get("data", {})
                    
                    if not goods_dict:
                        print(f"    第 {page_index} 页无数据，停止搜索")
                        break
                    
                    # 提取商品信息（精确过滤）
                    page_count = 0
                    page_excluded = 0
                    for good_id, item in goods_dict.items():
                        if good_id:
                            item_name = item.get("name", "")
                            
                            # 使用新的过滤函数
                            if self.should_filter_item(item_name, item_type):
                                page_excluded += 1
                                excluded_count += 1
                                continue
                            
                            # 精确过滤：检查是否属于当前物品类型
                            if self.is_valid_item_for_type(item_name, item_type):
                                all_items_info[str(good_id)] = {
                                    "good_id": str(good_id),
                                    "name": item_name,
                                    "market_hash_name": item.get("market_hash_name", ""),
                                    "keyword": keyword
                                }
                                page_count += 1
                            else:
                                page_excluded += 1
                                excluded_count += 1
                    
                    print(f"    第 {page_index} 页找到 {page_count} 个有效商品，排除 {page_excluded} 个")
                    
                    page_index += 1
                    
                    # 增加搜索页数限制，但给予更多时间
                    if page_index > 20:  # 增加到20页
                        print(f"    已达到最大页数限制（20页），停止搜索")
                        break
                    
                    # 添加延迟，避免API限制
                    time.sleep(1)
                        
                except Exception as e:
                    print(f"    获取第{page_index}页失败：{e}")
                    time.sleep(5)  # 失败后等待更长时间
                    break
        
        print(f"  总共找到 {len(all_items_info)} 个 {item_type} 相关商品")
        print(f"  排除 {excluded_count} 个不相关商品")
        
        # 保存到缓存
        self.save_cached_items(item_type, all_items_info)
        
        return all_items_info
    
    def save_cached_items(self, knife_type: str, items_info: Dict[str, Any]):
        """保存缓存到文件"""
        # 获取物品类型所属的类别
        category = self.get_category_for_item_type(knife_type)
        
        # 创建类别目录
        category_dir = os.path.join(self.cache_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        
        # 缓存文件路径：cache/类别/物品类型_items_cache.json
        cache_file = os.path.join(category_dir, f"{knife_type}_items_cache.json")
        
        cache_data = {
            "knife_type": knife_type,
            "category": category,
            "cache_time": datetime.now().isoformat(),
            "total_items": len(items_info),
            "items": items_info
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"  💾 缓存已保存到：{cache_file}")
        except Exception as e:
            print(f"  ❌ 保存缓存失败：{e}")
    
    def load_cached_items(self, knife_type: str) -> Dict[str, Any]:
        """从文件加载缓存"""
        # 获取物品类型所属的类别
        category = self.get_category_for_item_type(knife_type)
        
        # 缓存文件路径：cache/类别/物品类型_items_cache.json
        cache_file = os.path.join(self.cache_dir, category, f"{knife_type}_items_cache.json")
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                print(f"  📂 从缓存加载：{cache_file}")
                return cache_data
            except Exception as e:
                print(f"  ❌ 加载缓存失败：{e}")
        
        return None
    
    def validate_existing_cache(self, knife_type: str) -> Dict[str, Any]:
        """验证现有缓存的数据准确性"""
        cache_data = self.load_cached_items(knife_type)
        if not cache_data:
            return {'valid': False, 'error': '缓存不存在'}
        
        items = cache_data.get('items', {})
        invalid_items = []
        valid_items = {}
        
        for good_id, item in items.items():
            item_name = item.get('name', '')
            if not self.is_valid_item_for_knife_type(item_name, knife_type):
                invalid_items.append({
                    'good_id': good_id,
                    'name': item_name
                })
            else:
                valid_items[good_id] = item
        
        return {
            'valid': len(invalid_items) == 0,
            'total_items': len(items),
            'valid_items': len(valid_items),
            'invalid_items': len(invalid_items),
            'invalid_items_list': invalid_items
        }
    
    def build_all_caches(self, knife_types: List[str] = None, validate_only: bool = False, category: str = None):
        """构建所有刀型的缓存"""
        if category:
            # 如果指定了类别，只处理该类别下的物品类型
            item_types = list(ITEM_CATEGORIES.get(category, {}).keys())
            if not item_types:
                print(f"❌ 未找到类别：{category}")
                return {}
        elif knife_types is None:
            # 如果没有指定类别和物品类型，处理所有物品类型
            item_types = []
            for cat_items in ITEM_CATEGORIES.values():
                item_types.extend(list(cat_items.keys()))
        else:
            # 如果指定了物品类型列表
            item_types = knife_types
        
        if validate_only:
            print(f"🔍 验证 {len(item_types)} 种物品类型的缓存...")
        else:
            print(f"🚀 开始构建 {len(item_types)} 种物品类型的缓存...")
        print(f"⏰ 开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        results = {}
        
        for i, item_type in enumerate(item_types, 1):
            # 获取物品类型的关键词
            all_types = self.get_all_item_types()
            if item_type not in all_types:
                print(f"⚠️ 未知物品类型：{item_type}")
                continue
            
            keywords = all_types[item_type]
            category_name = self.get_category_for_item_type(item_type)
            
            print(f"\n{'='*60}")
            print(f"📦 [{i}/{len(item_types)}] 处理 {category_name} - {item_type}")
            print(f"{'='*60}")
            
            try:
                if validate_only:
                    # 只验证现有缓存
                    validation = self.validate_existing_cache(item_type)
                    results[item_type] = validation
                    
                    if validation['valid']:
                        print(f"✅ {item_type} 缓存验证通过")
                        print(f"   - 有效商品：{validation['valid_items']} 个")
                    else:
                        print(f"❌ {item_type} 缓存验证失败")
                        print(f"   - 总商品：{validation['total_items']} 个")
                        print(f"   - 有效商品：{validation['valid_items']} 个")
                        print(f"   - 无效商品：{validation['invalid_items']} 个")
                        
                        # 显示前几个无效商品
                        for invalid_item in validation['invalid_items_list'][:5]:
                            print(f"     ❌ {invalid_item['good_id']}: {invalid_item['name']}")
                        
                        if len(validation['invalid_items_list']) > 5:
                            print(f"     ... 还有 {len(validation['invalid_items_list']) - 5} 个无效商品")
                else:
                    # 检查是否已有缓存
                    cache_data = self.load_cached_items(item_type)
                    if cache_data and 'items' in cache_data and len(cache_data['items']) > 0:
                        print(f"✅ {item_type} 已有缓存，跳过构建")
                        print(f"   - 缓存商品数量：{len(cache_data['items'])} 个")
                        print(f"   - 缓存时间：{cache_data.get('cache_time', '未知')}")
                        
                        results[item_type] = {
                            'success': True,
                            'items_count': len(cache_data['items']),
                            'duration': 0,
                            'category': category_name,
                            'skipped': True
                        }
                        continue
                    
                    # 重新构建缓存
                    start_time = time.time()
                    
                    # 搜索并缓存商品
                    items_info = self.search_and_cache_items_generic(item_type, keywords)
                    
                    end_time = time.time()
                    duration = end_time - start_time
                    
                    results[item_type] = {
                        'success': True,
                        'items_count': len(items_info),
                        'duration': duration,
                        'category': category_name
                    }
                    
                    print(f"✅ {item_type} 缓存构建完成")
                    print(f"   - 商品数量：{len(items_info)} 个")
                    print(f"   - 耗时：{duration:.2f} 秒")
                
            except Exception as e:
                print(f"❌ {item_type} 处理失败：{e}")
                results[item_type] = {
                    'success': False,
                    'error': str(e),
                    'category': category_name
                }
            
            # 在物品类型之间添加延迟
            if i < len(item_types) and not validate_only:
                print(f"⏳ 等待 5 秒后继续下一个物品类型...")
                time.sleep(5)
        
        # 打印总结
        print(f"\n{'='*60}")
        if validate_only:
            print("📊 缓存验证总结")
        else:
            print("📊 缓存构建总结")
        print(f"{'='*60}")
        
        if validate_only:
            valid_count = sum(1 for r in results.values() if r.get('valid', False))
            total_items = sum(r.get('valid_items', 0) for r in results.values())
            invalid_items = sum(r.get('invalid_items', 0) for r in results.values())
            
            print(f"✅ 验证通过：{valid_count}/{len(item_types)} 种物品类型")
            print(f"📦 有效商品：{total_items} 个")
            print(f"❌ 无效商品：{invalid_items} 个")
            
            for item_type, result in results.items():
                if result.get('valid', False):
                    print(f"  ✅ {result.get('category', '未知')} - {item_type}: {result['valid_items']} 个有效商品")
                else:
                    print(f"  ❌ {result.get('category', '未知')} - {item_type}: {result['invalid_items']} 个无效商品")
        else:
            success_count = sum(1 for r in results.values() if r.get('success', False))
            skipped_count = sum(1 for r in results.values() if r.get('skipped', False))
            total_items = sum(r.get('items_count', 0) for r in results.values() if r.get('success', False))
            
            print(f"✅ 成功构建：{success_count}/{len(item_types)} 种物品类型")
            if skipped_count > 0:
                print(f"⏭️ 跳过已有缓存：{skipped_count} 种物品类型")
            print(f"📦 总商品数：{total_items} 个")
            
            for item_type, result in results.items():
                if result.get('success', False):
                    if result.get('skipped', False):
                        print(f"  ⏭️ {result.get('category', '未知')} - {item_type}: {result['items_count']} 个商品 (已缓存)")
                    else:
                        print(f"  ✅ {result.get('category', '未知')} - {item_type}: {result['items_count']} 个商品 ({result['duration']:.2f}s)")
                else:
                    print(f"  ❌ {result.get('category', '未知')} - {item_type}: {result.get('error', 'Unknown error')}")
        
        print(f"\n🎉 处理完成！")
        print(f"⏰ 结束时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return results

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="构建所有物品类型的缓存（支持匕首、探员、手枪、步枪、手套等类别）")
    parser.add_argument("--token", default=API_TOKEN, help="CSQAQ API Token")
    parser.add_argument("--knives", nargs="+", help="指定要处理的物品类型（默认全部）")
    parser.add_argument("--category", choices=["匕首", "探员", "手枪", "步枪", "手套"], help="指定要处理的物品类别")
    parser.add_argument("--validate-only", action="store_true", help="只验证现有缓存，不重新构建")
    
    args = parser.parse_args()
    
    if not args.token:
        raise SystemExit("需要提供API Token")
    
    # 构建缓存
    builder = CacheBuilder(args.token)
    
    if args.category:
        # 处理指定类别
        knife_types = None
        category = args.category
        print(f"🎯 处理类别：{category}")
    else:
        # 处理指定物品类型或全部
        knife_types = args.knives
        category = None
        if knife_types:
            print(f"🎯 处理物品类型：{', '.join(knife_types)}")
        else:
            print(f"🎯 处理所有物品类型")
    
    results = builder.build_all_caches(knife_types, validate_only=args.validate_only, category=category)
    
    print(f"\n🎉 处理完成！")

if __name__ == "__main__":
    main()
