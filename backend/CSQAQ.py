# csqaq_client.py
# pip install requests tenacity
import os, json, time, typing as T, logging, requests
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

# 导入配置文件
try:
    from config import API_TOKEN, BASE_URL, QPS, TIMEOUT, validate_config
except ImportError:
    # 如果配置文件不存在，使用默认值
    API_TOKEN = os.getenv("CSQAQ_TOKEN", "YOUR_API_TOKEN_HERE")
    BASE_URL = "https://api.csqaq.com/api/v1"
    QPS = 1.0
    TIMEOUT = 10.0
    def validate_config():
        if API_TOKEN == "YOUR_API_TOKEN_HERE":
            print("❌ 配置错误：请设置有效的API Token")
            print("请创建 config.py 文件或设置环境变量 CSQAQ_TOKEN")
            return False
        return True

Json = T.Dict[str, T.Any]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

DEFAULT_BASE_URL = BASE_URL

# TODO：把右侧字符串替换成你文档上的“真实路径”（只改这里！）
ENDPOINTS = {
    # 1) 饰品指数
    "index_home":          ("/current_data", "GET"),          # 获取首页相关数据
    "index_detail":        ("/sub_data", "GET"),              # 获取指数详情数据
    "index_kline":         ("/sub/kline", "GET"),             # 获取指数k线图

    # 2) 饰品详情
    "get_good_id":         ("/info/get_good_id", "POST"),     # body: {page_index, page_size, search}
    "search_suggest":      ("/search/suggest", "GET"),        # params: text
    "good_detail":         ("/info/good", "GET"),             # params: id
    "batch_price":         ("/goods/getPriceByMarketHashName", "POST"), # body: {marketHashNameList: [...]}
    "good_chart":          ("/info/chart", "POST"),           # body: {good_id, key, platform, period, style}

    # 3) 涨跌/热1排行 (待确认准确接口)
    # "rank_list":           ("/info/get_rank_list", "POST"),   # body: {rank_type, page_index, page_size}
    # "hot_series_list":     ("/hot/series/list", "POST"),      # body: {series_id, page_index, page_size}
    # "hot_series_detail":   ("/hot/series/detail", "GET"),     # params: series_id, id
    # "hot_rank":            ("/hot/rank", "POST"),             # body: {page_index, page_size}

    # 4) 挂刀行情 (待确认准确接口)
    # "knife_queue_detail":  ("/knife/queue/detail", "POST"),   # body: {id, ...filters}

    # 5) 成交数据
    "vol_data_info":       ("/info/vol_data_info", "POST"),   # body: {}
    "vol_data_detail":     ("/info/vol_data_detail", "POST"), # body: {vol_id, is_weapon, start_day}

    # 6) 排行榜和列表
    "get_rank_list":       ("/info/get_rank_list", "POST"),   # body: {page_index, page_size, show_recently_price, filter}
    "get_page_list":       ("/info/get_page_list", "POST"),   # body: {page_index, page_size, search, filter}
    "get_series_list":     ("/info/get_series_list", "POST"), # body: {}
    "get_series_detail":   ("/info/get_series_detail", "GET"), # params: series_id
    "get_popular_goods":   ("/info/get_popular_goods", "POST"), # body: {}

    # 7) 挂刀行情
    "exchange_detail":     ("/info/exchange_detail", "POST"), # body: {page_index, res, platforms, sort_by, min_price, max_price, turnover}
}

@dataclass
class CsqaqClient:
    api_token: str
    base_url: str = DEFAULT_BASE_URL
    qps: float = QPS
    timeout: float = TIMEOUT
    last_call_ts: float = 0.0

    def _headers(self) -> Json:
        return {"ApiToken": self.api_token, "Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}

    def _rate_limit(self):
        need = 1.0 / max(self.qps, 0.001)
        delta = time.time() - self.last_call_ts
        if delta < need:
            time.sleep(need - delta)
        self.last_call_ts = time.time()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1.0, max=5.0),
        retry=retry_if_exception_type((requests.RequestException,))
    )
    def _request(self, key: str, *, params: Json = None, data: Json = None) -> Json:
        if key not in ENDPOINTS:
            raise ValueError(f"Unknown endpoint key: {key}")
        path, method = ENDPOINTS[key]
        url = self.base_url.rstrip("/") + path
        self._rate_limit()

        logging.info("→ %s %s params=%s data=%s", method, url, params, data)
        if method == "GET":
            resp = requests.get(url, headers=self._headers(), params=params or {}, timeout=self.timeout)
        else:
            # 修复POST请求的数据格式
            json_data = json.dumps(data or {}, ensure_ascii=False)
            resp = requests.post(url, headers=self._headers(), json=data or {}, timeout=self.timeout)

        logging.info("← status=%s", resp.status_code)
        # 更友好的错误提示
        if resp.status_code == 404:
            raise RuntimeError(f"404 Not Found: {url}（很可能是路径跟文档不一致，去 ENDPOINTS 修正）")
        if resp.status_code == 403:
            raise RuntimeError("403 Forbidden：检查 ApiToken/白名单IP 是否正确")
        if resp.status_code == 401:
            raise RuntimeError("401 Unauthorized：ApiToken 无效或未在 Header 传入")
        resp.raise_for_status()

        try:
            j = resp.json()
        except Exception:
            raise RuntimeError(f"非 JSON 响应：{resp.text[:300]}")

        if isinstance(j, dict) and "code" in j and j.get("code") not in (0, 200, None):
            raise RuntimeError(f"业务错误 code={j.get('code')} msg={j.get('msg')}")
        return j

    # ===== 指数 =====
    def index_home(self) -> Json:
        return self._request("index_home")

    def index_detail(self, index_id: T.Union[int, str]) -> Json:
        return self._request("index_detail", params={"id": index_id, "type": "daily"})

    def index_kline(self, index_id: T.Union[int, str], period="1day", start: int = None, end: int = None) -> Json:
        params = {"id": index_id, "type": period}
        if start is not None: params["start"] = start
        if end is not None: params["end"] = end
        return self._request("index_kline", params=params)

    # ===== 饰品详情/ID =====
    def get_good_id(self, search: str, page_index: int = 1, page_size: int = 20) -> Json:
        """获取饰品ID信息"""
        return self._request("get_good_id", data={
            "page_index": page_index,
            "page_size": page_size,
            "search": search
        })

    def search_suggest(self, text: str) -> Json:
        """饰品名称联想查询"""
        return self._request("search_suggest", params={"text": text})

    def good_detail(self, good_id: T.Union[int, str]) -> Json:
        """获取单件饰品详情"""
        return self._request("good_detail", params={"id": good_id})

    def batch_price(self, market_hash_names: T.List[str]) -> Json:
        """批量获取饰品价格"""
        return self._request("batch_price", data={"marketHashNameList": market_hash_names})

    def good_chart(self, good_id: T.Union[int, str], key: str, platform: int = 1, 
                   period: str = "1095", style: str = "all_style") -> Json:
        """获取饰品图表数据"""
        return self._request("good_chart", data={
            "good_id": str(good_id),
            "key": key,
            "platform": platform,
            "period": period,
            "style": style
        })

    # ===== 成交数据 =====
    def vol_data_info(self) -> Json:
        """获取实时交易量数据信息"""
        return self._request("vol_data_info", data={})

    def vol_data_detail(self, vol_id: T.Union[int, str], is_weapon: bool, start_day: str) -> Json:
        """获取成交量图表/磨损信息

        参数:
        - vol_id: 成交量标识
        - is_weapon: 是否为武器（True/False）
        - start_day: 起始日期，格式 YYYY-MM-DD
        """
        return self._request("vol_data_detail", data={
            "vol_id": int(vol_id),
            "is_weapon": bool(is_weapon),
            "start_day": start_day
        })

    # ===== 排行榜和列表 =====
    def get_rank_list(self, page_index: int = 1, page_size: int = 15, 
                     show_recently_price: bool = False, filter_dict: Json = None) -> Json:
        """获取排行榜单信息
        
        参数:
        - page_index: 页码
        - page_size: 每页数量
        - show_recently_price: 是否显示最近价格
        - filter_dict: 过滤条件字典
        """
        data = {
            "page_index": page_index,
            "page_size": page_size,
            "show_recently_price": show_recently_price
        }
        if filter_dict:
            data["filter"] = filter_dict
        return self._request("get_rank_list", data=data)

    def get_page_list(self, page_index: int = 1, page_size: int = 18, 
                     search: str = "", filter_dict: Json = None) -> Json:
        """获取饰品列表信息
        
        参数:
        - page_index: 页码
        - page_size: 每页数量
        - search: 搜索关键词
        - filter_dict: 过滤条件字典
        """
        data = {
            "page_index": page_index,
            "page_size": page_size,
            "search": search
        }
        if filter_dict:
            data["filter"] = filter_dict
        return self._request("get_page_list", data=data)

    def get_series_list(self) -> Json:
        """获取热门系列饰品列表"""
        return self._request("get_series_list", data={})

    def get_series_detail(self, series_id: T.Union[int, str]) -> Json:
        """获取单件热门系列饰品详情
        
        参数:
        - series_id: 系列ID
        """
        return self._request("get_series_detail", params={"series_id": series_id})

    def get_popular_goods(self) -> Json:
        """获取饰品热度排名（前500件热门饰品）"""
        return self._request("get_popular_goods", data={})

    # ===== 挂刀行情 =====
    def exchange_detail(self, page_index: int = 1, res: int = 0, platforms: str = "BUFF-YYYP",
                       sort_by: int = 1, min_price: float = 1, max_price: float = 5000, 
                       turnover: int = 10) -> Json:
        """获取挂刀行情详情信息
        
        参数:
        - page_index: 页码
        - res: 分辨率/筛选条件
        - platforms: 平台组合，如 "BUFF-YYYP"
        - sort_by: 排序方式
        - min_price: 最低价格
        - max_price: 最高价格
        - turnover: 成交量要求
        """
        return self._request("exchange_detail", data={
            "page_index": page_index,
            "res": res,
            "platforms": platforms,
            "sort_by": sort_by,
            "min_price": min_price,
            "max_price": max_price,
            "turnover": turnover
        })

    # ===== 排行/热1 (待确认准确接口) =====
    # def rank_list(self, rank_type="price", page=1, size=50) -> Json:
    #     return self._request("rank_list", data={"rank_type": rank_type, "page_index": page, "page_size": size})

    # def hot_series_list(self, series_id: T.Union[int, str], page=1, size=50) -> Json:
    #     return self._request("hot_series_list", data={"series_id": series_id, "page_index": page, "page_size": size})

    # def hot_series_detail(self, series_id: T.Union[int, str], item_id: T.Union[int, str]) -> Json:
    #     return self._request("hot_series_detail", params={"series_id": series_id, "id": item_id})

    # def hot_rank(self, page=1, size=50) -> Json:
    #     return self._request("hot_rank", data={"page_index": page, "page_size": size})

    # ===== 挂刀 (待确认准确接口) =====
    # def knife_queue_detail(self, item_id: T.Union[int, str], **filters) -> Json:
    #     body = {"id": item_id}
    #     body.update(filters or {})
    #     return self._request("knife_queue_detail", data=body)

    # ===== 成交 (待确认准确接口) =====
    # def volume_realtime(self) -> Json:
    #     return self._request("volume_realtime")

    # def volume_hist(self, item_id: T.Union[int, str], start: int = None, end: int = None) -> Json:
    #     body = {"id": item_id}
    #     if start is not None: body["start"] = start
    #     if end is not None:   body["end"] = end
    #     return self._request("volume_hist", data=body)


# ========== 自检 Demo ==========
if __name__ == "__main__":
    # 验证配置
    if not validate_config():
        exit(1)
    
    client = CsqaqClient(api_token=API_TOKEN)

    # 1) 指数三连
    try:
        print("[index_home]", json.dumps(client.index_home(), ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("index_home error: %s", e)

    try:
        print("[index_detail]", json.dumps(client.index_detail(index_id=1), ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("index_detail error: %s", e)

    try:
        print("[index_kline]", json.dumps(client.index_kline(index_id=1, period="1d"), ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("index_kline error: %s", e)

    # 2) 饰品搜索 → 详情 → 价格 → 图表
    try:
        # 搜索饰品ID
        good_ids = client.get_good_id("蝴蝶刀", page_index=1, page_size=5)
        print("[get_good_id]", json.dumps(good_ids, ensure_ascii=False)[:300])
        
        # 联想查询
        suggest = client.search_suggest("杀猪刀")
        print("[search_suggest]", json.dumps(suggest, ensure_ascii=False)[:300])
        
        # 获取第一个饰品的详情
        if good_ids and 'data' in good_ids and good_ids['data']:
            first_good = good_ids['data'][0]
            good_id = first_good.get('id')
            if good_id:
                print("[good_detail]", json.dumps(client.good_detail(good_id), ensure_ascii=False)[:300])
                
                # 获取图表数据
                chart_data = client.good_chart(good_id, "sell_price", platform=1, period="1095")
                print("[good_chart]", json.dumps(chart_data, ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("item flow error: %s", e)

    # 3) 批量价格查询
    try:
        market_names = [
            "★ Bowie Knife",
            "★ Huntsman Knife | Tiger Tooth (Factory New)",
            "AWP | Snake Camo (Factory New)"
        ]
        batch_prices = client.batch_price(market_names)
        print("[batch_price]", json.dumps(batch_prices, ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("batch_price error: %s", e)

    # 4) 成交数据
    try:
        print("[vol_data_info]", json.dumps(client.vol_data_info(), ensure_ascii=False)[:300])
        print("[vol_data_detail]", json.dumps(client.vol_data_detail(vol_id=326, is_weapon=True, start_day="2024-06-26"), ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("volume data error: %s", e)

    # 5) 排行榜和列表
    try:
        # 获取排行榜
        rank_filter = {
            "排序": ["价格_售价减求购价(百分比)_升序(BUFF)"]
        }
        print("[get_rank_list]", json.dumps(client.get_rank_list(page_index=1, page_size=5, filter_dict=rank_filter), ensure_ascii=False)[:300])
        
        # 获取饰品列表
        page_filter = {
            "类别": ["unusual"],
            "外观": ["崭新出厂"],
            "类型": ["不限_匕首"]
        }
        print("[get_page_list]", json.dumps(client.get_page_list(page_index=1, page_size=5, search="蝴蝶", filter_dict=page_filter), ensure_ascii=False)[:300])
        
        # 获取热门系列
        print("[get_series_list]", json.dumps(client.get_series_list(), ensure_ascii=False)[:300])
        
        # 获取系列详情
        print("[get_series_detail]", json.dumps(client.get_series_detail(series_id=1), ensure_ascii=False)[:300])
        
        # 获取热门饰品
        print("[get_popular_goods]", json.dumps(client.get_popular_goods(), ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("rank and list error: %s", e)

    # 6) 挂刀行情
    try:
        print("[exchange_detail]", json.dumps(client.exchange_detail(page_index=1, platforms="BUFF-YYYP", min_price=1, max_price=5000, turnover=10), ensure_ascii=False)[:300])
    except Exception as e:
        logging.error("exchange detail error: %s", e)