# CSBOT Ubuntu服务器快速部署指南

## 🚀 一键部署

### 1. 上传文件到服务器

```bash
# 在本地打包项目
tar -czf csbot-backend.tar.gz backend/

# 上传到服务器
scp csbot-backend.tar.gz user@your-server:/home/user/

# 在服务器上解压
ssh user@your-server
cd /home/user
tar -xzf csbot-backend.tar.gz
cd backend
```

### 2. 运行部署脚本

```bash
# 给脚本执行权限
chmod +x deploy_server.sh

# 运行部署脚本
sudo ./deploy_server.sh
```

### 3. 启动服务

```bash
# 启动所有服务
./start_csbot.sh

# 检查服务状态
./status_csbot.sh
```

## 📋 部署检查清单

### 部署前检查
- [ ] Ubuntu 18.04+ 系统
- [ ] 至少2GB内存
- [ ] 至少5GB磁盘空间
- [ ] 网络连接正常
- [ ] sudo权限

### 部署后验证
- [ ] API服务正常运行
- [ ] Auto Run服务正常运行
- [ ] Nginx反向代理正常
- [ ] 防火墙配置正确
- [ ] 日志文件正常生成

## 🔧 常用管理命令

### 服务管理
```bash
# 启动服务
./start_csbot.sh

# 停止服务
./stop_csbot.sh

# 重启服务
./restart_csbot.sh

# 查看状态
./status_csbot.sh
```

### 日志查看
```bash
# API日志
./logs_csbot.sh api

# Auto Run日志
./logs_csbot.sh auto

# Nginx日志
./logs_csbot.sh nginx
```

### 系统监控
```bash
# 系统资源监控
./monitor_system.sh

# API功能测试
./test_api.sh
```

### 数据备份
```bash
# 创建备份
./backup_data.sh

# 恢复数据
./restore_data.sh <backup-file>
```

## 🌐 访问地址

部署完成后，可以通过以下地址访问：

- **API服务**: `http://your-server-ip:5000`
- **HTTP服务**: `http://your-server-ip`
- **API文档**: `http://your-server-ip:5000/api/health`

## 🔍 故障排除

### 服务无法启动
```bash
# 检查服务状态
sudo systemctl status csbot-api.service
sudo systemctl status csbot-auto-run.service

# 查看详细日志
sudo journalctl -u csbot-api.service -f
sudo journalctl -u csbot-auto-run.service -f
```

### 端口被占用
```bash
# 检查端口使用
sudo netstat -tlnp | grep :5000

# 杀死占用进程
sudo kill -9 <PID>
```

### 权限问题
```bash
# 修复权限
sudo chown -R csbot:csbot /var/log/csbot
sudo chown -R csbot:csbot /var/run/csbot
```

## 📞 获取帮助

如果遇到问题，请提供以下信息：

1. **系统信息**
   ```bash
   lsb_release -a
   python3 --version
   ```

2. **服务状态**
   ```bash
   ./status_csbot.sh
   ```

3. **错误日志**
   ```bash
   ./logs_csbot.sh api
   ./logs_csbot.sh auto
   ```

4. **系统资源**
   ```bash
   ./monitor_system.sh
   ```

## 🎯 下一步

部署完成后，建议：

1. **配置SSL证书** (Let's Encrypt)
2. **设置自动备份**
3. **配置监控告警**
4. **优化性能参数**
5. **设置日志轮转**

详细配置请参考 `README_SERVER.md`。
