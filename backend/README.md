# CSQAQ 后端服务文档

## 📋 概述

CSQAQ后端是一个基于Flask的RESTful API服务，为饰品数据分析可视化系统提供数据支持。系统集成了CSQAQ API，提供饰品市场数据、K线图、排行榜、交易量分析等功能。

## 🏗️ 架构设计

### 目录结构
```
backend/
├── app.py              # Flask主应用
├── CSQAQ.py            # CSQAQ API客户端
├── config.py           # 配置文件
├── requirements.txt    # Python依赖
└── README.md          # 本文档
```

### 核心组件

#### 1. Flask应用 (`app.py`)
- **功能**: 提供Web API接口，处理前端请求
- **端口**: 8080 (默认)
- **模板路径**: `../frontend/templates`
- **静态文件路径**: `../frontend/static`

#### 2. CSQAQ客户端 (`CSQAQ.py`)
- **功能**: 封装CSQAQ API调用，提供统一的接口
- **特性**: 
  - 自动重试机制 (最多5次)
  - 速率限制 (0.5 QPS)
  - 错误处理
  - 请求日志记录

#### 3. 配置管理 (`config.py`)
- **功能**: 集中管理API配置
- **配置项**: Token、Base URL、QPS限制、超时时间

## 🔧 安装与配置

### 1. 环境要求
- Python 3.7+
- pip

### 2. 安装依赖
```bash
cd backend
pip install -r requirements.txt
```

### 3. 配置API Token
编辑 `config.py` 文件：
```python
API_TOKEN = "your_api_token_here"
```

或设置环境变量：
```bash
export CSQAQ_TOKEN="your_api_token_here"
```

### 4. 验证配置
```python
python -c "from config import validate_config; validate_config()"
```

## 🚀 启动服务

### 方法1: 直接启动
```bash
cd backend
python app.py
```

### 方法2: 使用启动脚本
```bash
# 在项目根目录
./start.sh
```

### 方法3: 使用run.py
```bash
# 在项目根目录
python run.py
```

## 📡 API接口文档

### 1. 仪表板数据
```
GET /api/dashboard
```
**功能**: 获取首页仪表板数据
**返回**: 大盘指数、热门饰品、成交数据

### 2. 饰品搜索
```
GET /api/search?q={query}&page={page}&size={size}
```
**功能**: 搜索饰品
**参数**:
- `q`: 搜索关键词
- `page`: 页码 (默认1)
- `size`: 每页数量 (默认20)

### 3. 饰品详情
```
GET /api/item/{item_id}
```
**功能**: 获取饰品详细信息
**参数**:
- `item_id`: 饰品ID

### 4. 排行榜
```
GET /api/rankings?page={page}&size={size}&filter={filter}
```
**功能**: 获取饰品排行榜
**参数**:
- `page`: 页码
- `size`: 每页数量
- `filter`: 筛选条件

### 5. 热门系列
```
GET /api/series
GET /api/series/{series_id}
```
**功能**: 获取热门系列列表和详情

### 6. 挂刀行情
```
GET /api/exchange?page={page}&platforms={platforms}&min_price={min}&max_price={max}
```
**功能**: 获取挂刀行情数据

### 7. 成交数据
```
GET /api/volume
GET /api/volume/{vol_id}?is_weapon={bool}&start_day={date}
```
**功能**: 获取实时成交量和详细数据

### 8. K线图数据
```
GET /api/kline/index/{index_id}?period={period}&start={start}&end={end}
GET /api/kline/item/{item_id}?key={key}&platform={platform}&period={period}
```
**功能**: 获取大盘指数和饰品K线图数据
**参数**:
- `period`: 时间周期 (1hour, 1day, 1week, 1month)
- `key`: 数据类型 (sell_price, buy_price, etc.)
- `platform`: 平台 (1=BUFF, 2=YYYP, 3=Steam)

### 9. 联想搜索
```
GET /api/suggest?text={text}
```
**功能**: 提供饰品名称联想搜索

## 🔌 CSQAQ API集成

### 支持的接口

#### 饰品指数
- `index_home()`: 获取首页数据
- `index_detail()`: 获取指数详情
- `index_kline()`: 获取指数K线图

#### 饰品详情
- `get_good_id()`: 搜索饰品ID
- `search_suggest()`: 联想搜索
- `good_detail()`: 获取饰品详情
- `batch_price()`: 批量获取价格
- `good_chart()`: 获取饰品图表数据

#### 排行榜和列表
- `get_rank_list()`: 获取排行榜
- `get_page_list()`: 获取饰品列表
- `get_series_list()`: 获取热门系列
- `get_series_detail()`: 获取系列详情
- `get_popular_goods()`: 获取热门饰品

#### 交易数据
- `vol_data_info()`: 获取成交数据
- `vol_data_detail()`: 获取成交详情
- `exchange_detail()`: 获取挂刀行情

### 错误处理
- **401 Unauthorized**: Token无效或IP未白名单
- **429 Too Many Requests**: 请求频率过高
- **422 Unprocessable Entity**: 参数错误
- **500 Internal Server Error**: 服务器错误

### 重试机制
- 最大重试次数: 5次
- 重试间隔: 指数退避 (1-5秒)
- 仅对网络异常重试

## 📊 数据格式

### 通用响应格式
```json
{
    "success": true,
    "data": {...},
    "message": "操作成功"
}
```

### K线图数据格式
```json
{
    "t": 1640995200000,  // 时间戳
    "o": 100.5,          // 开盘价
    "h": 105.2,          // 最高价
    "l": 98.3,           // 最低价
    "c": 103.1,          // 收盘价
    "v": 1500            // 成交量
}
```

## 🔒 安全配置

### 1. API Token管理
- 使用环境变量存储敏感信息
- 定期轮换Token
- 限制Token权限

### 2. 请求限制
- QPS限制: 0.5 (每秒0.5个请求)
- 超时设置: 10秒
- 自动重试机制

### 3. 错误处理
- 详细的错误日志
- 用户友好的错误信息
- 异常捕获和恢复

## 📝 日志配置

### 日志级别
- INFO: 正常操作日志
- ERROR: 错误信息
- DEBUG: 调试信息 (开发环境)

### 日志格式
```
2024-01-01 12:00:00 INFO 请求信息
2024-01-01 12:00:01 ERROR 错误详情
```

## 🛠️ 开发指南

### 添加新接口
1. 在 `CSQAQ.py` 中添加新的API方法
2. 在 `app.py` 中添加对应的路由
3. 更新本文档

### 调试模式
```bash
export FLASK_ENV=development
export FLASK_DEBUG=1
python app.py
```

### 测试API
```bash
# 测试首页数据
curl http://localhost:8080/api/dashboard

# 测试搜索
curl "http://localhost:8080/api/search?q=蝴蝶刀"

# 测试K线图
curl "http://localhost:8080/api/kline/index/1?period=1day"
```

## 🚨 故障排除

### 常见问题

#### 1. 401 Unauthorized
- 检查API Token是否正确
- 确认IP是否在白名单中
- 验证Token是否过期

#### 2. 429 Too Many Requests
- 降低请求频率
- 检查QPS配置
- 使用重试机制

#### 3. 连接超时
- 检查网络连接
- 增加超时时间
- 验证API地址

#### 4. 数据格式错误
- 检查请求参数
- 验证数据格式
- 查看API文档

### 调试命令
```bash
# 检查配置
python -c "from config import validate_config; validate_config()"

# 测试API连接
python -c "from CSQAQ import CsqaqClient; client = CsqaqClient('your_token'); print(client.index_home())"

# 查看日志
tail -f logs/app.log
```

## 📈 性能优化

### 1. 缓存策略
- 考虑添加Redis缓存
- 实现数据缓存机制
- 减少重复API调用

### 2. 数据库集成
- 考虑添加数据库存储
- 实现数据持久化
- 优化查询性能

### 3. 异步处理
- 使用异步框架 (FastAPI)
- 实现异步API调用
- 提高并发性能

## 🔄 版本历史

### v2.0 (当前版本)
- ✅ 完整的API集成
- ✅ K线图支持 (1小时、日、周、月)
- ✅ 滚轮缩放功能
- ✅ 联想搜索
- ✅ 错误处理和重试机制
- ✅ 前后端分离架构

### v1.0
- ✅ 基础API集成
- ✅ 简单Web界面
- ✅ 基本数据展示

## 📞 技术支持

如有问题，请检查：
1. 配置文件是否正确
2. 网络连接是否正常
3. API Token是否有效
4. 日志文件中的错误信息

---

**最后更新**: 2024年1月
**版本**: v2.0
**状态**: ✅ 生产就绪
