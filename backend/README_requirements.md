# 后端依赖库说明

## 概述

`requirements.txt` 文件包含了CSBOT后端项目所需的所有Python库依赖。

## 核心依赖库

### Web框架和API
- **Flask==2.3.3**: Web应用框架
- **flask-cors==6.0.1**: 跨域资源共享支持
- **Werkzeug==2.3.7**: WSGI工具库

### HTTP请求和重试机制
- **requests==2.31.0**: HTTP请求库
- **tenacity==8.2.3**: 重试机制库

### 数据处理和分析
- **pandas>=1.3.0**: 数据处理和分析库
- **numpy>=1.21.0**: 数值计算库
- **pyarrow>=6.0.0**: 高性能数据格式支持
- **fastparquet>=0.8.0**: Parquet文件格式支持

### 进度条和用户界面
- **tqdm>=4.62.0**: 进度条显示库

### 时间处理
- **python-dateutil>=2.8.0**: 日期时间处理库
- **pytz>=2023.3**: 时区处理库

### 任务调度
- **apscheduler>=3.11.0**: 高级任务调度器
- **schedule>=1.2.0**: 简单任务调度库

### 数据可视化
- **matplotlib>=3.4.0**: 基础图表功能

## 安装方法

### 1. 基础安装
```bash
pip install -r requirements.txt
```

### 2. 虚拟环境安装（推荐）
```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. Conda环境安装
```bash
# 创建conda环境
conda create -n csbot python=3.9

# 激活环境
conda activate csbot

# 安装依赖
pip install -r requirements.txt
```

## 可选依赖库

如果需要扩展功能，可以考虑安装以下可选库：

### 机器学习支持
```bash
pip install scikit-learn>=1.0.0
```

### 科学计算
```bash
pip install scipy>=1.7.0
```

### 统计建模
```bash
pip install statsmodels>=0.13.0
```

### 环境变量管理
```bash
pip install python-dotenv>=0.19.0
```

### 日志格式化
```bash
pip install colorlog>=6.6.0
```

### 配置文件处理
```bash
pip install PyYAML>=6.0
```

### 数据库支持
```bash
pip install sqlalchemy>=1.4.0
```

### 缓存支持
```bash
pip install redis>=4.0.0
```

### 异步支持
```bash
pip install aiohttp>=3.8.0
```

### 测试框架
```bash
pip install pytest>=6.0.0 pytest-cov>=3.0.0
```

### 代码质量工具
```bash
pip install flake8>=4.0.0 black>=22.0.0 isort>=5.10.0
```

### 类型检查
```bash
pip install mypy>=0.950
```

## 版本兼容性

- **Python版本**: 3.8+
- **操作系统**: Windows, macOS, Linux
- **架构**: x86_64, ARM64

## 常见问题

### 1. 安装失败
如果安装过程中遇到问题，可以尝试：
```bash
# 升级pip
pip install --upgrade pip

# 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

### 2. 版本冲突
如果遇到版本冲突，可以尝试：
```bash
# 使用--no-deps选项
pip install --no-deps -r requirements.txt

# 或者逐个安装
pip install Flask==2.3.3
pip install flask-cors==6.0.1
# ... 其他库
```

### 3. 权限问题
如果遇到权限问题，可以尝试：
```bash
# 使用--user选项
pip install --user -r requirements.txt

# 或者使用sudo（Linux/macOS）
sudo pip install -r requirements.txt
```

## 更新依赖

### 1. 更新单个库
```bash
pip install --upgrade 库名
```

### 2. 更新所有库
```bash
pip install --upgrade -r requirements.txt
```

### 3. 生成新的requirements.txt
```bash
pip freeze > requirements_new.txt
```

## 开发环境设置

对于开发环境，建议安装额外的开发工具：

```bash
# 安装开发依赖
pip install -r requirements.txt
pip install pytest>=6.0.0
pip install black>=22.0.0
pip install flake8>=4.0.0
pip install mypy>=0.950
```

## 生产环境部署

对于生产环境，建议：

1. 使用虚拟环境
2. 固定版本号（避免使用>=）
3. 定期更新安全补丁
4. 使用requirements.txt.lock文件锁定版本

```bash
# 生成锁定文件
pip freeze > requirements.txt.lock

# 安装锁定版本
pip install -r requirements.txt.lock
```
