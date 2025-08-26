# config.py
# CSQAQ API 配置文件

import os

# API Token 配置
# 请将下面的值替换为您的有效API Token
API_TOKEN = os.getenv("CSQAQ_TOKEN", "MXSSN1G7W5L5P8N1V4J7K0X6")

# API 基础配置
BASE_URL = "https://api.csqaq.com/api/v1"
QPS = 0.3  # 每秒请求数限制（进一步降低以避免429错误）
TIMEOUT = 30.0  # 请求超时时间（秒，增加以适应高延迟网络）

# 验证配置
def validate_config():
    """验证配置是否正确"""
    if API_TOKEN == "YOUR_API_TOKEN_HERE" or not API_TOKEN or API_TOKEN.strip() == "":
        print("❌ 配置错误：请设置有效的API Token")
        print("\n📋 设置方法：")
        print("方法1：设置环境变量")
        print("   export CSQAQ_TOKEN='your_api_token_here'")
        print("方法2：直接修改 config.py 文件")
        print("   将 API_TOKEN 的值改为您的实际Token")
        print("\n🔗 获取Token：")
        print("请访问 https://csqaq.com 注册并获取您的API Token")
        return False
    
    print("✅ 配置验证通过")
    print(f"🔑 使用Token: {API_TOKEN[:8]}...{API_TOKEN[-4:] if len(API_TOKEN) > 12 else '***'}")
    return True
