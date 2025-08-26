#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
后台进程检查和管理的便捷脚本
"""

import subprocess
import sys
import os
from datetime import datetime

def run_command(cmd):
    """运行命令并返回结果"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        return f"错误：{e}"

def check_csbot_processes():
    """检查CSBOT相关进程"""
    print("🔍 检查CSBOT后台进程")
    print("=" * 50)
    
    # 获取所有Python进程
    ps_output = run_command("ps aux | grep -E '(auto_run|build_database)' | grep -v grep")
    
    if not ps_output:
        print("✅ 没有发现CSBOT相关进程在运行")
        return
    
    print("📊 当前运行的CSBOT进程：")
    print("-" * 50)
    
    lines = ps_output.split('\n')
    csbot_processes = []
    
    for line in lines:
        if line.strip():
            parts = line.split()
            if len(parts) >= 11:
                pid = parts[1]
                cpu = parts[2]
                mem = parts[3]
                time = parts[8]
                command = ' '.join(parts[10:])
                
                # 提取关键信息
                if 'auto_run.py' in command:
                    process_type = "🕐 主控制脚本"
                elif 'build_database.py' in command:
                    process_type = "📊 数据库构建"
                else:
                    process_type = "❓ 其他进程"
                
                csbot_processes.append({
                    'pid': pid,
                    'cpu': cpu,
                    'mem': mem,
                    'time': time,
                    'command': command,
                    'type': process_type
                })
                
                print(f"PID: {pid} | CPU: {cpu}% | 内存: {mem}% | 运行时间: {time}")
                print(f"类型: {process_type}")
                print(f"命令: {command}")
                print("-" * 50)
    
    return csbot_processes

def show_system_info():
    """显示系统信息"""
    print("\n💻 系统信息：")
    print("-" * 30)
    
    # CPU使用率
    cpu_info = run_command("top -l 1 | grep 'CPU usage'")
    print(f"CPU使用率: {cpu_info}")
    
    # 内存使用率
    mem_info = run_command("top -l 1 | grep 'PhysMem'")
    print(f"内存使用: {mem_info}")
    
    # 磁盘使用率
    disk_info = run_command("df -h . | tail -1")
    print(f"磁盘使用: {disk_info}")

def show_management_options():
    """显示管理选项"""
    print("\n🛠️  进程管理选项：")
    print("-" * 30)
    print("1. 查看所有Python进程: ps aux | grep python")
    print("2. 停止特定进程: kill <PID>")
    print("3. 停止所有CSBOT进程: pkill -f 'auto_run\|build_database'")
    print("4. 查看进程树: pstree <PID>")
    print("5. 查看进程详细信息: ps -p <PID> -o pid,ppid,etime,pcpu,pmem,command")

def main():
    """主函数"""
    print("🚀 CSBOT进程管理器")
    print("=" * 50)
    print(f"⏰ 检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查CSBOT进程
    processes = check_csbot_processes()
    
    # 显示系统信息
    show_system_info()
    
    # 显示管理选项
    show_management_options()
    
    if processes:
        print(f"\n📈 总结：发现 {len(processes)} 个CSBOT相关进程")
        
        # 分析进程状态
        auto_run_count = sum(1 for p in processes if 'auto_run.py' in p['command'])
        build_db_count = sum(1 for p in processes if 'build_database.py' in p['command'])
        
        print(f"  - 主控制脚本: {auto_run_count} 个")
        print(f"  - 数据库构建: {build_db_count} 个")
        
        if auto_run_count > 1:
            print("⚠️  警告：发现多个主控制脚本，建议停止重复的进程")
        if build_db_count > 1:
            print("⚠️  警告：发现多个数据库构建进程，建议停止重复的进程")
    else:
        print("\n✅ 系统状态正常，没有发现CSBOT进程")

if __name__ == "__main__":
    main()
