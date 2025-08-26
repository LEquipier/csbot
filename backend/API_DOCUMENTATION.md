# CSBOT iOS应用API文档

## 概述

CSBOT API为iOS应用提供完整的监控、调参和数据报告功能。所有接口都返回JSON格式数据，支持跨域请求。

**基础URL**: `http://localhost:5000/api`

## 认证

目前API不需要认证，但某些操作（如数据库更新）需要提供API Token。

## 响应格式

所有API响应都遵循以下格式：

```json
{
  "success": true,
  "data": {...},
  "message": "操作成功"
}
```

错误响应：

```json
{
  "error": "错误描述",
  "code": 400
}
```

## 1. 系统监控接口

### 1.1 健康检查
**GET** `/api/health`

检查API服务是否正常运行。

**响应示例**:
```json
{
  "status": "healthy",
  "timestamp": "2025-01-26T10:30:00",
  "version": "1.0.0"
}
```

### 1.2 系统状态
**GET** `/api/status`

获取系统整体状态信息。

**响应示例**:
```json
{
  "database_last_update": "2025-01-26 10:00:00",
  "analysis_last_run": "2025-01-26 10:15:00",
  "total_items": 1250,
  "active_positions": 3,
  "system_health": "healthy",
  "memory_usage": 0.65,
  "disk_usage": 0.45
}
```

### 1.3 性能指标
**GET** `/api/performance`

获取交易性能指标。

**响应示例**:
```json
{
  "total_return": 0.125,
  "win_rate": 0.68,
  "avg_holding_days": 8.5,
  "max_drawdown": 0.045,
  "sharpe_ratio": 1.25,
  "total_trades": 15
}
```

## 2. 市场分析接口

### 2.1 市场概览
**GET** `/api/market/overview`

获取市场整体概览信息。

**响应示例**:
```json
{
  "total_candidates": 12,
  "total_watchlist": 8,
  "platform_distribution": {
    "BUFF": 7,
    "YYYP": 5
  },
  "category_distribution": {
    "蝴蝶刀": 4,
    "M9刺刀": 3,
    "爪子刀": 2
  },
  "last_analysis": "2025-01-26 10:15",
  "analysis_mode": "适中",
  "insufficient_data_count": 25
}
```

### 2.2 当前分析结果
**GET** `/api/analysis/current`

获取最新的分析结果。

**响应示例**:
```json
{
  "asof": "2025-01-26 10:15",
  "mode": "适中",
  "lookback_hours": 336,
  "min_required_hours": 168,
  "buy_candidates": [...],
  "watchlist": [...],
  "sell_advice_for_holdings": [...],
  "locked_until_t7": [...],
  "insufficient_series": [...],
  "notes": [...]
}
```

### 2.3 运行分析
**POST** `/api/analysis/run`

手动运行分析。

**请求体**:
```json
{
  "mode": "适中",
  "topk": 8,
  "lookback_hours": 336,
  "root_dir": "dataset/匕首"
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "Analysis completed successfully",
  "result": {...}
}
```

## 3. 持仓管理接口

### 3.1 获取持仓
**GET** `/api/positions`

获取当前所有持仓信息。

**响应示例**:
```json
{
  "positions": [
    {
      "knife_type": "蝴蝶刀",
      "item_name": "13901_503_蝴蝶刀 StatTrak _ 伽玛多普勒 崭新出厂 _ Phase1",
      "platform": "BUFF",
      "qty": 1,
      "buy_price": 28000.0,
      "buy_time": "2025-08-22 14:30",
      "peak_ret": 0.025
    }
  ],
  "count": 1,
  "timestamp": "2025-01-26T10:30:00"
}
```

### 3.2 添加持仓
**POST** `/api/positions/add`

添加新的持仓记录。

**请求体**:
```json
{
  "knife": "蝴蝶刀",
  "item": "13901_503_蝴蝶刀 StatTrak _ 伽玛多普勒 崭新出厂 _ Phase1.csv",
  "platform": "BUFF",
  "qty": 1,
  "price": 28000.0,
  "time": "2025-08-22 14:30"
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "Position added successfully"
}
```

### 3.3 删除持仓
**DELETE** `/api/positions/{position_id}`

删除指定持仓。

**响应示例**:
```json
{
  "success": true,
  "message": "Position removed successfully",
  "removed_position": {...}
}
```

## 4. 数据库管理接口

### 4.1 更新数据库
**POST** `/api/database/update`

手动更新数据库。

**请求体**:
```json
{
  "api_token": "your_api_token_here"
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "Database updated successfully"
}
```

## 5. 配置管理接口

### 5.1 获取配置
**GET** `/api/config`

获取系统配置信息。

**响应示例**:
```json
{
  "modes": ["稳健", "适中", "激进"],
  "default_config": {
    "mode": "适中",
    "topk": 8,
    "lookback_hours": 336,
    "root_dir": "dataset/匕首"
  },
  "available_categories": ["匕首", "步枪", "手枪", "手套", "探员"]
}
```

### 5.2 更新配置
**POST** `/api/config/update`

更新系统配置。

**请求体**:
```json
{
  "mode": "激进",
  "topk": 12,
  "lookback_hours": 168
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "Configuration updated successfully"
}
```

## 6. 历史记录接口

### 6.1 获取历史记录
**GET** `/api/history?limit=10`

获取历史分析记录。

**查询参数**:
- `limit`: 返回记录数量（默认10）

**响应示例**:
```json
{
  "history": [
    {
      "timestamp": "20250126_101500",
      "mode": "适中",
      "buy_candidates_count": 12,
      "watchlist_count": 8,
      "sell_advice_count": 2
    }
  ],
  "total_records": 45
}
```

### 6.2 获取历史详情
**GET** `/api/history/{timestamp}`

获取特定历史记录的详细信息。

**响应示例**:
```json
{
  "asof": "2025-01-26 10:15",
  "mode": "适中",
  "buy_candidates": [...],
  "watchlist": [...],
  "sell_advice_for_holdings": [...]
}
```

## 7. 数据分析接口

### 7.1 趋势分析
**GET** `/api/analytics/trends?days=7`

获取趋势分析数据。

**查询参数**:
- `days`: 分析天数（默认7）

**响应示例**:
```json
{
  "trends": [
    {
      "date": "20250126",
      "buy_candidates": 12,
      "watchlist": 8,
      "sell_advice": 2
    }
  ],
  "period_days": 7
}
```

## 8. 数据导出接口

### 8.1 导出数据
**GET** `/api/export/data?type=current`

导出数据文件。

**查询参数**:
- `type`: 导出类型（`current` | `positions`）

**响应**: 文件下载

## 9. 通知接口

### 9.1 获取通知
**GET** `/api/notifications`

获取系统通知。

**响应示例**:
```json
{
  "notifications": [
    {
      "type": "info",
      "title": "Position Ready for Sale",
      "message": "蝴蝶刀 / 13901_503_蝴蝶刀 StatTrak _ 伽玛多普勒 崭新出厂 _ Phase1 has reached T+7",
      "timestamp": "2025-01-26T10:30:00"
    }
  ],
  "count": 1
}
```

## 错误代码

| 代码 | 描述 |
|------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

## 使用示例

### iOS Swift示例

```swift
import Foundation

class CSBOTAPI {
    private let baseURL = "http://localhost:5000/api"
    
    func getSystemStatus() async throws -> SystemStatus {
        let url = URL(string: "\(baseURL)/status")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try JSONDecoder().decode(SystemStatus.self, from: data)
    }
    
    func runAnalysis(config: AnalysisConfig) async throws -> AnalysisResult {
        let url = URL(string: "\(baseURL)/analysis/run")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let jsonData = try JSONEncoder().encode(config)
        request.httpBody = jsonData
        
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(AnalysisResult.self, from: data)
    }
    
    func getPositions() async throws -> [Position] {
        let url = URL(string: "\(baseURL)/positions")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let response = try JSONDecoder().decode(PositionsResponse.self, from: data)
        return response.positions
    }
}

// 数据模型
struct SystemStatus: Codable {
    let databaseLastUpdate: String?
    let analysisLastRun: String?
    let totalItems: Int
    let activePositions: Int
    let systemHealth: String
    
    enum CodingKeys: String, CodingKey {
        case databaseLastUpdate = "database_last_update"
        case analysisLastRun = "analysis_last_run"
        case totalItems = "total_items"
        case activePositions = "active_positions"
        case systemHealth = "system_health"
    }
}

struct AnalysisConfig: Codable {
    let mode: String
    let topk: Int
    let lookbackHours: Int
    let rootDir: String
    
    enum CodingKeys: String, CodingKey {
        case mode, topk
        case lookbackHours = "lookback_hours"
        case rootDir = "root_dir"
    }
}

struct Position: Codable {
    let knifeType: String
    let itemName: String
    let platform: String
    let qty: Int
    let buyPrice: Double
    let buyTime: String
    let peakRet: Double
    
    enum CodingKeys: String, CodingKey {
        case knifeType = "knife_type"
        case itemName = "item_name"
        case platform, qty
        case buyPrice = "buy_price"
        case buyTime = "buy_time"
        case peakRet = "peak_ret"
    }
}

struct PositionsResponse: Codable {
    let positions: [Position]
    let count: Int
    let timestamp: String
}
```

### React Native示例

```javascript
class CSBOTAPI {
    constructor() {
        this.baseURL = 'http://localhost:5000/api';
    }
    
    async getSystemStatus() {
        try {
            const response = await fetch(`${this.baseURL}/status`);
            return await response.json();
        } catch (error) {
            console.error('Error fetching system status:', error);
            throw error;
        }
    }
    
    async runAnalysis(config) {
        try {
            const response = await fetch(`${this.baseURL}/analysis/run`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(config),
            });
            return await response.json();
        } catch (error) {
            console.error('Error running analysis:', error);
            throw error;
        }
    }
    
    async getPositions() {
        try {
            const response = await fetch(`${this.baseURL}/positions`);
            return await response.json();
        } catch (error) {
            console.error('Error fetching positions:', error);
            throw error;
        }
    }
}

// 使用示例
const api = new CSBOTAPI();

// 获取系统状态
api.getSystemStatus().then(status => {
    console.log('System status:', status);
});

// 运行分析
api.runAnalysis({
    mode: '适中',
    topk: 8,
    lookback_hours: 336
}).then(result => {
    console.log('Analysis result:', result);
});
```

## 部署说明

### 本地开发
```bash
cd backend
python api_interface.py
```

### 生产环境
```bash
# 使用gunicorn部署
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 api_interface:app
```

### Docker部署
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "api_interface:app"]
```

## 注意事项

1. **CORS支持**: API已配置CORS，支持跨域请求
2. **错误处理**: 所有接口都有完善的错误处理
3. **日志记录**: 所有操作都会记录日志
4. **数据验证**: 输入数据会进行验证
5. **性能优化**: 支持并发请求处理

## 更新日志

- **v1.0.0**: 初始版本，包含基础监控和分析功能
- 支持系统状态监控
- 支持市场分析
- 支持持仓管理
- 支持历史记录查询
- 支持数据导出
- 支持通知系统
