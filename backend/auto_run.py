#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自动定时更新数据库脚本
每小时整点自动运行 build_database.py 来更新所有刀型的实时数据
"""

import os
import sys
import time
import schedule
import subprocess
import logging
import threading
import queue
import signal
import atexit
from datetime import datetime, timezone, timedelta
from typing import Optional
from tqdm import tqdm

# 添加父目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from config import API_TOKEN

class ProgressMonitor:
    """进度监控器，用于显示实时进度条"""
    
    def __init__(self, total_steps: int = 100, description: str = "处理中"):
        self.total_steps = total_steps
        self.current_step = 0
        self.description = description
        self.pbar = None
        self.lock = threading.Lock()
        
    def start(self):
        """启动进度条"""
        self.pbar = tqdm(
            total=self.total_steps,
            desc=self.description,
            unit="项",
            ncols=100,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
        )
        
    def update(self, step: int = 1, description: str = None):
        """更新进度"""
        with self.lock:
            if self.pbar:
                if description:
                    self.pbar.set_description(description)
                self.pbar.update(step)
                self.current_step += step
                
    def set_description(self, description: str):
        """设置描述"""
        with self.lock:
            if self.pbar:
                self.pbar.set_description(description)
                
    def set_total(self, total: int):
        """设置总数"""
        with self.lock:
            if self.pbar:
                self.pbar.total = total
                self.total_steps = total
                
    def close(self):
        """关闭进度条"""
        with self.lock:
            if self.pbar:
                self.pbar.close()
                self.pbar = None

class AutoDatabaseUpdater:
    def __init__(self, api_token: str = None):
        self.api_token = api_token or API_TOKEN
        self.script_dir = os.path.dirname(__file__)
        self.build_script = os.path.join(self.script_dir, "Model", "build_database.py")
        self.model_script = os.path.join(self.script_dir, "Model", "model.py")
        
        # 进程管理
        self.current_process = None
        self.progress_monitor = None
        self.shutdown_requested = False
        
        # 设置信号处理
        self.setup_signal_handlers()
        
        # 设置退出时的清理
        atexit.register(self.cleanup)
        
        # 设置日志
        self.setup_logging()
    
    def setup_signal_handlers(self):
        """设置信号处理器"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"⛔ 收到信号 {signum}，正在优雅关闭...")
        self.shutdown_requested = True
        self.cleanup()
        sys.exit(0)
    
    def cleanup(self):
        """清理资源"""
        try:
            # 关闭进度条
            if self.progress_monitor:
                self.progress_monitor.close()
            
            # 终止当前进程
            if self.current_process and self.current_process.poll() is None:
                self.logger.info("🛑 正在终止子进程...")
                self.current_process.terminate()
                
                # 等待进程结束
                try:
                    self.current_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.logger.warning("⚠️ 子进程未在10秒内结束，强制终止")
                    self.current_process.kill()
                    self.current_process.wait()
                
                self.logger.info("✅ 子进程已终止")
        except Exception as e:
            self.logger.error(f"❌ 清理过程中发生错误：{e}")
        
    def setup_logging(self):
        """设置日志配置"""
        log_dir = os.path.join(self.script_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, "auto_update.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def get_beijing_time(self) -> str:
        """获取北京时间"""
        utc_now = datetime.now(timezone.utc)
        beijing_tz = timezone(timedelta(hours=8))
        beijing_time = utc_now.astimezone(beijing_tz)
        return beijing_time.strftime("%Y-%m-%d %H:%M:%S")
    
    def parse_progress_from_output(self, output: str, progress_info: dict):
        """从输出中解析进度信息"""
        import re
        
        # 解析总物品数量
        if "开始记录" in output and "种物品类型" in output:
            match = re.search(r'(\d+) 种物品类型', output)
            if match:
                progress_info['total_items'] = int(match.group(1))
                self.logger.info(f"📊 检测到总物品类型数量：{progress_info['total_items']}")
        
        # 解析当前处理的物品类型
        if "开始记录" in output and "实时数据" in output:
            match = re.search(r'开始记录 (.+?) - (.+?) 实时数据', output)
            if match:
                category = match.group(1)
                item_type = match.group(2)
                progress_info['current_item_type'] = f"{category} - {item_type}"
                self.logger.info(f"🔄 开始处理：{progress_info['current_item_type']}")
        
        # 解析已处理的物品数量
        if "记录总结" in output:
            match = re.search(r'成功记录：(\d+)/(\d+) 种物品类型', output)
            if match:
                progress_info['processed_items'] = int(match.group(1))
                progress_info['total_items'] = int(match.group(2))
                self.logger.info(f"✅ 处理完成：{progress_info['processed_items']}/{progress_info['total_items']}")
        
        # 解析单个物品类型的处理进度
        if "最终处理" in output and "个商品" in output:
            match = re.search(r'最终处理 (\d+) 个商品', output)
            if match:
                items_count = int(match.group(1))
                self.logger.info(f"📦 当前物品类型商品数量：{items_count}")
        
        # 解析处理完成信息
        if "数据记录完成" in output:
            match = re.search(r'处理商品：(\d+) 个', output)
            if match:
                processed_count = int(match.group(1))
                progress_info['processed_items'] += 1  # 完成一个物品类型
                self.logger.info(f"✅ 完成物品类型，已处理：{progress_info['processed_items']}")
        
        # 解析单个物品类型的完成信息
        if "数据记录完成" in output and "处理商品：" in output:
            # 这个物品类型处理完成，增加计数
            progress_info['processed_items'] += 1
            self.logger.info(f"✅ 物品类型处理完成，已处理：{progress_info['processed_items']}")
    
    def check_database_exists(self) -> bool:
        """检查数据库是否存在"""
        try:
            dataset_dir = os.path.join(self.script_dir, "Model", "dataset")
            
            # 检查dataset目录是否存在
            if not os.path.exists(dataset_dir):
                self.logger.info("📁 数据库目录不存在")
                return False
            
            # 检查是否有数据文件
            data_files = []
            for root, dirs, files in os.walk(dataset_dir):
                for file in files:
                    if file.endswith('.csv'):
                        data_files.append(os.path.join(root, file))
            
            if not data_files:
                self.logger.info("📊 数据库目录存在但没有数据文件")
                return False
            
            self.logger.info(f"✅ 数据库存在，发现 {len(data_files)} 个数据文件")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 检查数据库时发生错误：{e}")
            return False
        
    def run_build_database(self) -> bool:
        """运行 build_database.py 脚本（带进度条）"""
        try:
            self.logger.info("🚀 开始自动更新数据库")
            self.logger.info(f"⏰ 北京时间：{self.get_beijing_time()}")
            
            # 构建命令 - 使用API合规版本（严格遵循1次/秒限制）
            cmd = [
                sys.executable,
                os.path.join(self.script_dir, "Model", "build_database.py"),
                "--token", self.api_token
            ]
            
            self.logger.info(f"📝 执行命令：{' '.join(cmd)}")
            
            # 启动子进程 - 捕获输出以解析进度
            self.current_process = subprocess.Popen(
                cmd,
                cwd=self.script_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # 进度跟踪变量（使用字典以便在函数间共享）
            progress_info = {
                'total_items': 0,
                'processed_items': 0,
                'current_item_type': "",
                'start_time': time.time()
            }
            
            # 创建进度监控器（初始设置为100，后续会根据实际情况调整）
            self.progress_monitor = ProgressMonitor(total_steps=100, description="初始化中...")
            self.progress_monitor.start()
            
            # 实时读取输出并解析进度
            while True:
                # 检查是否请求关闭
                if self.shutdown_requested:
                    break
                
                # 检查进程是否结束
                if self.current_process.poll() is not None:
                    break
                
                # 读取输出
                output = self.current_process.stdout.readline()
                if output:
                    output = output.strip()
                    
                    # 打印输出到控制台
                    print(output)
                    
                    # 解析进度信息
                    self.parse_progress_from_output(output, progress_info)
                    
                    # 更新进度条
                    if progress_info['total_items'] > 0:
                        # 设置进度条总数为实际的总物品类型数量
                        if self.progress_monitor.total_steps != progress_info['total_items']:
                            self.progress_monitor.set_total(progress_info['total_items'])
                        
                        # 更新描述和进度
                        self.progress_monitor.set_description(f"处理 {progress_info['current_item_type']}")
                        
                        # 直接设置到当前进度
                        current_progress = self.progress_monitor.current_step
                        if progress_info['processed_items'] > current_progress:
                            self.progress_monitor.update(progress_info['processed_items'] - current_progress)
                    else:
                        # 如果还没有确定总数，显示时间进度
                        elapsed = time.time() - progress_info['start_time']
                        self.progress_monitor.set_description(f"初始化中... ({elapsed:.0f}s)")
                        if elapsed > 30:  # 30秒后开始显示时间进度
                            time_progress = min(int(elapsed / 300 * 100), 50)  # 假设最多5分钟初始化
                            current_progress = self.progress_monitor.current_step
                            if time_progress > current_progress:
                                self.progress_monitor.update(time_progress - current_progress)
                
                time.sleep(0.1)  # 短暂休眠避免CPU占用过高
            
            # 等待进程完成
            stdout, stderr = self.current_process.communicate()
            
            # 完成进度条
            self.progress_monitor.set_description("完成")
            self.progress_monitor.update(self.progress_monitor.total_steps - self.progress_monitor.current_step)
            self.progress_monitor.close()
            
            if self.current_process.returncode == 0:
                self.logger.info("✅ 数据库更新成功")
                return True
            else:
                self.logger.error(f"❌ 数据库更新失败，返回码：{self.current_process.returncode}")
                if stdout:
                    self.logger.error(f"输出：{stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            if self.progress_monitor:
                self.progress_monitor.close()
            self.logger.error("❌ 数据库更新超时（超过1小时）")
            return False
        except Exception as e:
            if self.progress_monitor:
                self.progress_monitor.close()
            self.logger.error(f"❌ 数据库更新异常：{e}")
            return False
            
    def run_model_analysis(self) -> bool:
        """运行 model.py 进行分析（带进度条）"""
        try:
            self.logger.info("📊 开始运行模型分析")
            
            # 构建命令 - 使用适中模式，分析前8个候选
            cmd = [
                sys.executable,
                self.model_script,
                "--mode", "适中",
                "--topk", "8",
                "--lookback", "336"  # 14天数据
            ]
            
            self.logger.info(f"📝 执行分析命令：{' '.join(cmd)}")
            
            # 创建进度监控器
            progress_monitor = ProgressMonitor(total_steps=50, description="模型分析中")
            progress_monitor.start()
            
            # 启动子进程
            process = subprocess.Popen(
                cmd,
                cwd=self.script_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # 实时读取输出并更新进度
            start_time = time.time()
            last_update = start_time
            
            while True:
                # 检查进程是否结束
                if process.poll() is not None:
                    break
                
                # 读取输出
                output = process.stdout.readline()
                if output:
                    output = output.strip()
                    # 解析输出中的进度信息
                    if "分析" in output or "计算" in output:
                        progress_monitor.set_description("数据分析中")
                        progress_monitor.update(1)
                    elif "加载" in output:
                        progress_monitor.set_description("加载数据")
                    elif "预测" in output:
                        progress_monitor.set_description("生成预测")
                    elif "保存" in output:
                        progress_monitor.set_description("保存结果")
                    elif "开始" in output:
                        progress_monitor.set_description("开始分析")
                    elif "完成" in output:
                        progress_monitor.set_description("分析完成")
                        progress_monitor.update(5)
                
                # 定期更新进度（即使没有输出）
                current_time = time.time()
                if current_time - last_update > 3:  # 每3秒更新一次
                    elapsed = current_time - start_time
                    progress_monitor.set_description(f"分析中 ({elapsed:.0f}s)")
                    progress_monitor.update(1)
                    last_update = current_time
                
                time.sleep(0.1)  # 短暂休眠避免CPU占用过高
            
            # 等待进程完成
            stdout, stderr = process.communicate()
            
            # 完成进度条
            progress_monitor.set_description("完成")
            progress_monitor.update(progress_monitor.total_steps - progress_monitor.current_step)
            progress_monitor.close()
            
            if process.returncode == 0:
                self.logger.info("✅ 模型分析成功")
                if stdout:
                    self.logger.info(f"分析结果：\n{stdout}")
                return True
            else:
                self.logger.error(f"❌ 模型分析失败，返回码：{process.returncode}")
                if stderr:
                    self.logger.error(f"错误输出：\n{stderr}")
                if stdout:
                    self.logger.error(f"标准输出：\n{stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            if 'progress_monitor' in locals():
                progress_monitor.close()
            self.logger.error("❌ 模型分析超时（超过30分钟）")
            return False
        except Exception as e:
            if 'progress_monitor' in locals():
                progress_monitor.close()
            self.logger.error(f"❌ 模型分析异常：{e}")
            return False
            
    def scheduled_update(self):
        """定时更新任务"""
        self.logger.info("=" * 60)
        self.logger.info("🕐 开始执行定时更新任务")
        
        # 第一步：更新数据库
        db_success = self.run_build_database()
        
        if db_success:
            self.logger.info("✅ 数据库更新完成，开始运行模型分析")
            
            # 第二步：运行模型分析
            model_success = self.run_model_analysis()
            
            if model_success:
                self.logger.info("🎉 定时更新任务完成（数据库更新 + 模型分析）")
            else:
                self.logger.error("⚠️ 数据库更新成功，但模型分析失败")
        else:
            self.logger.error("💥 数据库更新失败，跳过模型分析")
            
        self.logger.info("=" * 60)
        
    def start_scheduler(self, run_immediately: bool = False):
        """启动定时任务调度器"""
        self.logger.info("🚀 启动自动数据库更新服务")
        self.logger.info(f"⏰ 当前北京时间：{self.get_beijing_time()}")
        self.logger.info("📅 计划：每小时整点自动更新数据库")
        
        # 检查数据库是否存在
        self.logger.info("🔍 检查数据库状态...")
        database_exists = self.check_database_exists()
        
        if not database_exists:
            self.logger.info("📊 数据库不存在，立即开始构建...")
            # 立即构建数据库
            build_success = self.run_build_database()
            if build_success:
                self.logger.info("✅ 数据库构建完成")
                # 构建完成后，从下一个整点开始定时更新
                self.logger.info("⏰ 数据库构建完成，将从下一个整点开始定时更新")
            else:
                self.logger.error("❌ 数据库构建失败")
                return
        elif run_immediately:
            self.logger.info("⚡ 立即执行模式：先运行一次数据库更新，然后等待下一个整点")
            # 立即执行一次
            immediate_success = self.run_once()
            if immediate_success:
                self.logger.info("✅ 初始数据库更新完成")
            else:
                self.logger.error("❌ 初始数据库更新失败，但将继续定时任务")
        
        # 每小时的整点运行
        schedule.every().hour.at(":00").do(self.scheduled_update)
        
        self.logger.info("✅ 定时任务已设置，等待下一个整点...")
        
        # 显示下次运行时间
        next_run = schedule.next_run()
        if next_run:
            beijing_next = next_run.astimezone(timezone(timedelta(hours=8)))
            self.logger.info(f"⏰ 下次运行时间：{beijing_next.strftime('%Y-%m-%d %H:%M:%S')} (北京时间)")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)  # 每30秒检查一次
                
        except KeyboardInterrupt:
            self.logger.info("⛔ 收到中断信号，正在停止服务...")
        except Exception as e:
            self.logger.error(f"❌ 调度器异常：{e}")
        finally:
            self.logger.info("🛑 自动数据库更新服务已停止")
            
    def run_once(self):
        """立即运行一次更新和分析"""
        self.logger.info("🚀 立即运行数据库更新和模型分析")
        
        # 第一步：更新数据库
        db_success = self.run_build_database()
        
        if db_success:
            self.logger.info("✅ 数据库更新完成，开始运行模型分析")
            
            # 第二步：运行模型分析
            model_success = self.run_model_analysis()
            
            if model_success:
                self.logger.info("🎉 任务完成（数据库更新 + 模型分析）")
                return True
            else:
                self.logger.error("⚠️ 数据库更新成功，但模型分析失败")
                return False
        else:
            self.logger.error("💥 数据库更新失败，跳过模型分析")
            return False

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="自动定时更新数据库")
    parser.add_argument("--token", default=API_TOKEN, help="CSQAQ API Token")
    parser.add_argument("--once", action="store_true", help="立即运行一次更新（不启动定时任务）")
    parser.add_argument("--immediate", action="store_true", help="立即运行一次更新，然后启动定时任务")
    parser.add_argument("--daemon", action="store_true", help="以守护进程模式运行")
    
    args = parser.parse_args()
    
    if not args.token:
        print("❌ 需要提供API Token")
        return 1
        
    # 创建更新器
    updater = AutoDatabaseUpdater(args.token)

    if args.once:
        # 立即运行一次
        success = updater.run_once()
        return 0 if success else 1
    elif args.immediate:
        # 立即运行一次，然后启动定时任务
        if args.daemon:
            updater.logger.info("🤖 以守护进程模式运行")
        updater.start_scheduler(run_immediately=True)
        return 0
    else:
        # 启动定时任务（智能模式：自动检查数据库，不存在则构建）
        if args.daemon:
            updater.logger.info("🤖 以守护进程模式运行")
        
        updater.logger.info("🧠 智能模式：自动检查数据库状态")
        updater.start_scheduler(run_immediately=False)
        return 0

if __name__ == "__main__":
    exit(main())
