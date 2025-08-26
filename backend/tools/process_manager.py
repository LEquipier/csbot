#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
改进的进程管理脚本
提供更好的后台进程管理和清理功能
"""

import subprocess
import sys
import os
import signal
import time
from datetime import datetime

def run_command(cmd):
    """运行命令并返回结果"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        return f"错误：{e}"

def get_csbot_processes():
    """获取CSBOT相关进程"""
    ps_output = run_command("ps aux | grep -E '(auto_run|build_database)' | grep -v grep")
    processes = []
    
    if ps_output:
        lines = ps_output.split('\n')
        for line in lines:
            if line.strip():
                parts = line.split()
                if len(parts) >= 11:
                    processes.append({
                        'pid': parts[1],
                        'cpu': parts[2],
                        'mem': parts[3],
                        'time': parts[8],
                        'command': ' '.join(parts[10:])
                    })
    
    return processes

def show_processes():
    """显示当前进程"""
    print("🔍 当前CSBOT进程状态：")
    print("=" * 50)
    
    processes = get_csbot_processes()
    
    if not processes:
        print("✅ 没有发现CSBOT相关进程在运行")
        return processes
    
    for i, proc in enumerate(processes, 1):
        print(f"{i}. PID: {proc['pid']} | CPU: {proc['cpu']}% | 内存: {proc['mem']}% | 运行时间: {proc['time']}")
        print(f"   命令: {proc['command']}")
        print("-" * 50)
    
    return processes

def kill_process(pid):
    """终止指定进程"""
    try:
        # 先尝试优雅终止
        os.kill(int(pid), signal.SIGTERM)
        print(f"🔄 正在优雅终止进程 {pid}...")
        
        # 等待5秒
        time.sleep(5)
        
        # 检查是否还在运行
        if run_command(f"ps -p {pid}"):
            print(f"⚠️  进程 {pid} 仍在运行，强制终止...")
            os.kill(int(pid), signal.SIGKILL)
            time.sleep(1)
        
        if not run_command(f"ps -p {pid}"):
            print(f"✅ 进程 {pid} 已成功终止")
            return True
        else:
            print(f"❌ 无法终止进程 {pid}")
            return False
            
    except Exception as e:
        print(f"❌ 终止进程 {pid} 时发生错误：{e}")
        return False

def kill_all_csbot_processes():
    """终止所有CSBOT进程"""
    print("🛑 正在终止所有CSBOT进程...")
    
    processes = get_csbot_processes()
    if not processes:
        print("✅ 没有CSBOT进程需要终止")
        return True
    
    success_count = 0
    for proc in processes:
        if kill_process(proc['pid']):
            success_count += 1
    
    print(f"📊 终止结果：{success_count}/{len(processes)} 个进程已终止")
    return success_count == len(processes)

def start_auto_run():
    """启动auto_run脚本"""
    print("🚀 启动auto_run脚本...")
    
    # 检查是否已有进程在运行
    processes = get_csbot_processes()
    if processes:
        print("⚠️  发现已有CSBOT进程在运行：")
        for proc in processes:
            print(f"   PID {proc['pid']}: {proc['command']}")
        
        choice = input("是否要终止现有进程并重新启动？(y/N): ").strip().lower()
        if choice == 'y':
            kill_all_csbot_processes()
        else:
            print("❌ 取消启动")
            return False
    
    # 启动新进程
    try:
        cmd = f"cd '{os.getcwd()}' && python auto_run.py --daemon"
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✅ auto_run脚本已启动（后台模式）")
        time.sleep(2)
        show_processes()
        return True
    except Exception as e:
        print(f"❌ 启动失败：{e}")
        return False

def main():
    """主函数"""
    print("🛠️  CSBOT进程管理器")
    print("=" * 50)
    print(f"⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    while True:
        print("\n📋 可用操作：")
        print("1. 查看当前进程")
        print("2. 终止所有CSBOT进程")
        print("3. 启动auto_run脚本")
        print("4. 终止特定进程")
        print("5. 退出")
        
        choice = input("\n请选择操作 (1-5): ").strip()
        
        if choice == '1':
            show_processes()
        
        elif choice == '2':
            kill_all_csbot_processes()
        
        elif choice == '3':
            start_auto_run()
        
        elif choice == '4':
            processes = get_csbot_processes()
            if not processes:
                print("❌ 没有进程可以终止")
                continue
            
            print("\n当前进程：")
            for i, proc in enumerate(processes, 1):
                print(f"{i}. PID {proc['pid']}: {proc['command']}")
            
            try:
                pid_choice = input("请输入要终止的进程PID: ").strip()
                if pid_choice.isdigit():
                    kill_process(pid_choice)
                else:
                    print("❌ 无效的PID")
            except ValueError:
                print("❌ 无效的PID")
        
        elif choice == '5':
            print("👋 再见！")
            break
        
        else:
            print("❌ 无效选择，请重试")

if __name__ == "__main__":
    main()
