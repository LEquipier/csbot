# CSBOT iOS应用开发指南

## 概述

本指南将帮助您开发一个功能完整的iOS应用来监控CSBOT系统、调整参数和查看数据报告。

## 技术栈推荐

### 原生iOS开发
- **语言**: Swift 5.0+
- **框架**: SwiftUI + Combine
- **最低版本**: iOS 14.0+
- **架构**: MVVM

### 跨平台开发
- **React Native**: 使用JavaScript/TypeScript
- **Flutter**: 使用Dart语言

## 项目结构建议

```
CSBOT-iOS/
├── CSBOT-iOS/
│   ├── App/
│   │   ├── CSBOTApp.swift
│   │   └── ContentView.swift
│   ├── Models/
│   │   ├── SystemStatus.swift
│   │   ├── Position.swift
│   │   ├── AnalysisResult.swift
│   │   └── Notification.swift
│   ├── Views/
│   │   ├── Dashboard/
│   │   ├── Analysis/
│   │   ├── Positions/
│   │   ├── Settings/
│   │   └── Reports/
│   ├── ViewModels/
│   │   ├── DashboardViewModel.swift
│   │   ├── AnalysisViewModel.swift
│   │   └── PositionsViewModel.swift
│   ├── Services/
│   │   ├── APIService.swift
│   │   ├── DataService.swift
│   │   └── NotificationService.swift
│   └── Utils/
│       ├── Constants.swift
│       ├── Extensions.swift
│       └── Helpers.swift
├── CSBOT-iOSTests/
└── CSBOT-iOSUITests/
```

## 核心功能模块

### 1. 仪表板 (Dashboard)
- 系统状态概览
- 实时性能指标
- 快速操作按钮
- 通知中心

### 2. 市场分析 (Analysis)
- 当前分析结果展示
- 买入候选列表
- 观察名单
- 卖出建议
- 手动运行分析

### 3. 持仓管理 (Positions)
- 持仓列表
- 添加新持仓
- 持仓详情
- 收益跟踪

### 4. 历史记录 (History)
- 历史分析记录
- 趋势图表
- 数据导出

### 5. 设置 (Settings)
- 分析参数配置
- 通知设置
- 系统配置

## 数据模型设计

### SystemStatus.swift
```swift
struct SystemStatus: Codable, Identifiable {
    let id = UUID()
    let databaseLastUpdate: String?
    let analysisLastRun: String?
    let totalItems: Int
    let activePositions: Int
    let systemHealth: String
    let memoryUsage: Double
    let diskUsage: Double
    
    enum CodingKeys: String, CodingKey {
        case databaseLastUpdate = "database_last_update"
        case analysisLastRun = "analysis_last_run"
        case totalItems = "total_items"
        case activePositions = "active_positions"
        case systemHealth = "system_health"
        case memoryUsage = "memory_usage"
        case diskUsage = "disk_usage"
    }
}
```

### Position.swift
```swift
struct Position: Codable, Identifiable {
    let id = UUID()
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
```

### AnalysisResult.swift
```swift
struct AnalysisResult: Codable {
    let asof: String?
    let mode: String
    let lookbackHours: Int
    let minRequiredHours: Int
    let buyCandidates: [BuyCandidate]
    let watchlist: [WatchlistItem]
    let sellAdviceForHoldings: [SellAdvice]
    let lockedUntilT7: [LockedPosition]
    let insufficientSeries: [String]
    let notes: [String]
    
    enum CodingKeys: String, CodingKey {
        case asof, mode
        case lookbackHours = "lookback_hours"
        case minRequiredHours = "min_required_hours"
        case buyCandidates = "buy_candidates"
        case watchlist
        case sellAdviceForHoldings = "sell_advice_for_holdings"
        case lockedUntilT7 = "locked_until_t7"
        case insufficientSeries = "insufficient_series"
        case notes
    }
}

struct BuyCandidate: Codable, Identifiable {
    let id = UUID()
    let knifeType: String
    let itemName: String
    let platform: String
    let priceSell: Double?
    let priceBuy: Double?
    let spread: Double?
    let liqRatio24h: Double?
    let fastOverMid: Double?
    let midOverLong: Double?
    let crossRatio: Double?
    let score: Double
    let reason: String
    
    enum CodingKeys: String, CodingKey {
        case knifeType = "knife_type"
        case itemName = "item_name"
        case platform
        case priceSell = "price_sell"
        case priceBuy = "price_buy"
        case spread, liqRatio24h = "liq_ratio_24h"
        case fastOverMid = "fast_over_mid"
        case midOverLong = "mid_over_long"
        case crossRatio = "cross_ratio"
        case score, reason
    }
}
```

## API服务层

### APIService.swift
```swift
import Foundation
import Combine

class APIService: ObservableObject {
    private let baseURL = "http://localhost:5000/api"
    private var cancellables = Set<AnyCancellable>()
    
    // MARK: - System Status
    func getSystemStatus() -> AnyPublisher<SystemStatus, Error> {
        guard let url = URL(string: "\(baseURL)/status") else {
            return Fail(error: APIError.invalidURL).eraseToAnyPublisher()
        }
        
        return URLSession.shared.dataTaskPublisher(for: url)
            .map(\.data)
            .decode(type: SystemStatus.self, decoder: JSONDecoder())
            .receive(on: DispatchQueue.main)
            .eraseToAnyPublisher()
    }
    
    // MARK: - Analysis
    func getCurrentAnalysis() -> AnyPublisher<AnalysisResult, Error> {
        guard let url = URL(string: "\(baseURL)/analysis/current") else {
            return Fail(error: APIError.invalidURL).eraseToAnyPublisher()
        }
        
        return URLSession.shared.dataTaskPublisher(for: url)
            .map(\.data)
            .decode(type: AnalysisResult.self, decoder: JSONDecoder())
            .receive(on: DispatchQueue.main)
            .eraseToAnyPublisher()
    }
    
    func runAnalysis(config: AnalysisConfig) -> AnyPublisher<AnalysisResponse, Error> {
        guard let url = URL(string: "\(baseURL)/analysis/run") else {
            return Fail(error: APIError.invalidURL).eraseToAnyPublisher()
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            request.httpBody = try JSONEncoder().encode(config)
        } catch {
            return Fail(error: error).eraseToAnyPublisher()
        }
        
        return URLSession.shared.dataTaskPublisher(for: request)
            .map(\.data)
            .decode(type: AnalysisResponse.self, decoder: JSONDecoder())
            .receive(on: DispatchQueue.main)
            .eraseToAnyPublisher()
    }
    
    // MARK: - Positions
    func getPositions() -> AnyPublisher<PositionsResponse, Error> {
        guard let url = URL(string: "\(baseURL)/positions") else {
            return Fail(error: APIError.invalidURL).eraseToAnyPublisher()
        }
        
        return URLSession.shared.dataTaskPublisher(for: url)
            .map(\.data)
            .decode(type: PositionsResponse.self, decoder: JSONDecoder())
            .receive(on: DispatchQueue.main)
            .eraseToAnyPublisher()
    }
    
    func addPosition(position: AddPositionRequest) -> AnyPublisher<APIResponse, Error> {
        guard let url = URL(string: "\(baseURL)/positions/add") else {
            return Fail(error: APIError.invalidURL).eraseToAnyPublisher()
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            request.httpBody = try JSONEncoder().encode(position)
        } catch {
            return Fail(error: error).eraseToAnyPublisher()
        }
        
        return URLSession.shared.dataTaskPublisher(for: request)
            .map(\.data)
            .decode(type: APIResponse.self, decoder: JSONDecoder())
            .receive(on: DispatchQueue.main)
            .eraseToAnyPublisher()
    }
}

// MARK: - Error Types
enum APIError: Error, LocalizedError {
    case invalidURL
    case networkError
    case decodingError
    case serverError(String)
    
    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL"
        case .networkError:
            return "Network error occurred"
        case .decodingError:
            return "Failed to decode response"
        case .serverError(let message):
            return message
        }
    }
}
```

## ViewModel设计

### DashboardViewModel.swift
```swift
import Foundation
import Combine

class DashboardViewModel: ObservableObject {
    @Published var systemStatus: SystemStatus?
    @Published var performanceMetrics: PerformanceMetrics?
    @Published var marketOverview: MarketOverview?
    @Published var notifications: [Notification] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    
    private let apiService = APIService()
    private var cancellables = Set<AnyCancellable>()
    
    init() {
        loadDashboardData()
    }
    
    func loadDashboardData() {
        isLoading = true
        errorMessage = nil
        
        // 并行加载所有数据
        Publishers.Zip4(
            apiService.getSystemStatus(),
            apiService.getPerformance(),
            apiService.getMarketOverview(),
            apiService.getNotifications()
        )
        .receive(on: DispatchQueue.main)
        .sink(
            receiveCompletion: { [weak self] completion in
                self?.isLoading = false
                if case .failure(let error) = completion {
                    self?.errorMessage = error.localizedDescription
                }
            },
            receiveValue: { [weak self] status, metrics, overview, notifications in
                self?.systemStatus = status
                self?.performanceMetrics = metrics
                self?.marketOverview = overview
                self?.notifications = notifications
            }
        )
        .store(in: &cancellables)
    }
    
    func refreshData() {
        loadDashboardData()
    }
}
```

## UI设计建议

### 1. 仪表板设计
```swift
struct DashboardView: View {
    @StateObject private var viewModel = DashboardViewModel()
    
    var body: some View {
        NavigationView {
            ScrollView {
                LazyVGrid(columns: [
                    GridItem(.flexible()),
                    GridItem(.flexible())
                ], spacing: 16) {
                    // 系统状态卡片
                    SystemStatusCard(status: viewModel.systemStatus)
                    
                    // 性能指标卡片
                    PerformanceCard(metrics: viewModel.performanceMetrics)
                    
                    // 市场概览卡片
                    MarketOverviewCard(overview: viewModel.marketOverview)
                    
                    // 快速操作卡片
                    QuickActionsCard()
                }
                .padding()
            }
            .navigationTitle("仪表板")
            .refreshable {
                viewModel.refreshData()
            }
            .overlay(
                Group {
                    if viewModel.isLoading {
                        ProgressView("加载中...")
                    }
                }
            )
        }
    }
}
```

### 2. 分析结果展示
```swift
struct AnalysisView: View {
    @StateObject private var viewModel = AnalysisViewModel()
    
    var body: some View {
        NavigationView {
            List {
                Section("买入候选") {
                    ForEach(viewModel.analysisResult?.buyCandidates ?? []) { candidate in
                        BuyCandidateRow(candidate: candidate)
                    }
                }
                
                Section("观察名单") {
                    ForEach(viewModel.analysisResult?.watchlist ?? []) { item in
                        WatchlistRow(item: item)
                    }
                }
                
                Section("卖出建议") {
                    ForEach(viewModel.analysisResult?.sellAdviceForHoldings ?? []) { advice in
                        SellAdviceRow(advice: advice)
                    }
                }
            }
            .navigationTitle("市场分析")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("运行分析") {
                        viewModel.runAnalysis()
                    }
                }
            }
        }
    }
}
```

## 通知系统

### 本地通知
```swift
import UserNotifications

class NotificationService {
    static let shared = NotificationService()
    
    func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, error in
            if granted {
                print("通知权限已获取")
            } else {
                print("通知权限被拒绝")
            }
        }
    }
    
    func scheduleNotification(title: String, body: String, timeInterval: TimeInterval) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: timeInterval, repeats: false)
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: trigger)
        
        UNUserNotificationCenter.current().add(request)
    }
}
```

## 数据持久化

### Core Data模型
```swift
// 创建Core Data模型来缓存数据
extension Position {
    func toCoreData(context: NSManagedObjectContext) -> PositionEntity {
        let entity = PositionEntity(context: context)
        entity.knifeType = knifeType
        entity.itemName = itemName
        entity.platform = platform
        entity.qty = Int32(qty)
        entity.buyPrice = buyPrice
        entity.buyTime = buyTime
        entity.peakRet = peakRet
        return entity
    }
}
```

## 测试策略

### 单元测试
```swift
import XCTest
@testable import CSBOT_iOS

class APIServiceTests: XCTestCase {
    var apiService: APIService!
    
    override func setUp() {
        super.setUp()
        apiService = APIService()
    }
    
    func testGetSystemStatus() {
        let expectation = XCTestExpectation(description: "Get system status")
        
        apiService.getSystemStatus()
            .sink(
                receiveCompletion: { completion in
                    if case .failure(let error) = completion {
                        XCTFail("API call failed: \(error)")
                    }
                    expectation.fulfill()
                },
                receiveValue: { status in
                    XCTAssertNotNil(status)
                    XCTAssertNotNil(status.systemHealth)
                }
            )
            .store(in: &cancellables)
        
        wait(for: [expectation], timeout: 5.0)
    }
}
```

## 部署和发布

### 1. 开发环境配置
- 设置API服务器地址
- 配置调试模式
- 设置日志级别

### 2. 生产环境配置
- 使用HTTPS
- 配置API认证
- 设置错误监控

### 3. App Store发布
- 准备应用图标和截图
- 编写应用描述
- 配置隐私政策
- 提交审核

## 性能优化

### 1. 网络优化
- 使用缓存策略
- 实现请求去重
- 添加重试机制

### 2. UI优化
- 使用懒加载
- 实现分页加载
- 优化图片加载

### 3. 内存优化
- 及时释放资源
- 使用弱引用
- 避免循环引用

## 安全考虑

### 1. 网络安全
- 使用HTTPS
- 实现证书固定
- 添加请求签名

### 2. 数据安全
- 加密敏感数据
- 使用Keychain存储
- 实现数据脱敏

### 3. 代码安全
- 混淆关键代码
- 防止逆向工程
- 实现代码签名

## 监控和分析

### 1. 崩溃监控
- 集成Crashlytics
- 实现错误上报
- 添加性能监控

### 2. 用户行为分析
- 集成Analytics
- 跟踪用户路径
- 分析使用习惯

### 3. 性能监控
- 监控启动时间
- 跟踪内存使用
- 分析网络性能

## 总结

这个iOS应用将为CSBOT系统提供一个完整的移动端解决方案，包括：

1. **实时监控**: 系统状态、性能指标、市场数据
2. **参数调整**: 分析模式、阈值设置、配置管理
3. **数据报告**: 历史记录、趋势分析、数据导出
4. **持仓管理**: 持仓跟踪、收益计算、卖出建议
5. **通知系统**: 实时提醒、到期通知、异常警告

通过这个应用，用户可以随时随地监控和管理CSBOT系统，提高交易效率和决策质量。
