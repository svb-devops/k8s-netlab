"""
Smart Logger for K8S NetLab Project

自动收集运行时信息、错误、上下文，生成统一报告。
"""

import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SmartLogger:
    """智能日志收集器 - 自动收集错误和上下文"""

    def __init__(self, task_name: str):
        self.task_name = task_name
        self.start_time = datetime.now()

        self.logs: List[Dict] = []
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []
        self.successes: List[Dict] = []

        self.stats = {
            'total_operations': 0,
            'successful': 0,
            'failed': 0,
            'warnings': 0
        }

        self.reports_dir = Path("logs/reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self._setup_logging()

    def _setup_logging(self):
        """配置Python logging"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        self.logger = logging.getLogger(self.task_name)
        self.logger.setLevel(logging.INFO)

        # Close and remove any handlers from a previous use of this logger name to
        # prevent file descriptor leaks — Python's logging module caches loggers
        # globally, so the same task_name (e.g. create_vm_101) reused across VM
        # lifecycle cycles would otherwise accumulate one FileHandler per call.
        for old_handler in self.logger.handlers[:]:
            old_handler.close()
            self.logger.removeHandler(old_handler)

        # Directly attach a FileHandler to this logger so it always writes its
        # task log file, regardless of whether the root logger already has handlers
        # (logging.basicConfig is a no-op when root already has handlers).
        file_handler = logging.FileHandler(f'logs/{self.task_name}.log')
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        self.logger.addHandler(file_handler)

    def info(self, message: str, context: Optional[Dict] = None):
        """记录信息"""
        self.stats['total_operations'] += 1
        entry = {
            'timestamp': datetime.now().isoformat(),
            'level': 'INFO',
            'message': message,
            'context': context or {}
        }
        self.logs.append(entry)
        self.logger.info(message)

    def success(self, message: str, result: Any = None):
        """记录成功"""
        self.stats['successful'] += 1
        entry = {
            'timestamp': datetime.now().isoformat(),
            'message': message,
            'result': str(result) if result else None
        }
        self.successes.append(entry)
        self.logger.info(f"✓ {message}")

    def warning(self, message: str, details: Optional[str] = None):
        """记录警告"""
        self.stats['warnings'] += 1
        entry = {
            'timestamp': datetime.now().isoformat(),
            'message': message,
            'details': details
        }
        self.warnings.append(entry)
        self.logger.warning(f"⚠ {message}")

    def error(self, message: str, exception: Optional[Exception] = None):
        """记录错误 - 自动捕获堆栈和上下文"""
        self.stats['failed'] += 1

        stack_trace = None
        exc_type = None
        exc_value = None

        if exception:
            stack_trace = ''.join(traceback.format_exception(
                type(exception), exception, exception.__traceback__
            ))
            exc_type = type(exception).__name__
            exc_value = str(exception)

        error_entry = {
            'timestamp': datetime.now().isoformat(),
            'message': message,
            'exception_type': exc_type,
            'exception_value': exc_value,
            'stack_trace': stack_trace
        }

        self.errors.append(error_entry)
        self.logger.error(f"✗ {message} | {exc_type}: {exc_value}")

    def generate_report(self) -> str:
        """生成统一报告文件"""
        duration = (datetime.now() - self.start_time).total_seconds()

        report_filename = f"REPORT_{self.task_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        report_path = self.reports_dir / report_filename

        lines = []
        lines.append("=" * 80)
        lines.append("K8S NetLab - Smart Logger Report")
        lines.append(f"Task: {self.task_name}")
        lines.append(f"Generated: {datetime.now()}")
        lines.append("=" * 80)
        lines.append("")

        # 统计
        lines.append("📊 STATISTICS")
        lines.append(f"Duration: {duration:.2f}s")
        lines.append(f"Total: {self.stats['total_operations']}")
        lines.append(f"Success: {self.stats['successful']} ✓")
        lines.append(f"Failed: {self.stats['failed']} ✗")
        lines.append(f"Warnings: {self.stats['warnings']} ⚠")
        lines.append("")

        # 错误
        if self.errors:
            lines.append("🚨 ERRORS")
            lines.append("-" * 80)
            for i, err in enumerate(self.errors, 1):
                lines.append(f"\nError #{i}:")
                lines.append(f"  Time: {err['timestamp']}")
                lines.append(f"  Message: {err['message']}")
                lines.append(f"  Type: {err['exception_type']}")
                lines.append(f"  Value: {err['exception_value']}")
                if err['stack_trace']:
                    lines.append("\n  Stack Trace:")
                    lines.append(err['stack_trace'])
            lines.append("")

        # 警告
        if self.warnings:
            lines.append("⚠️  WARNINGS")
            for w in self.warnings:
                lines.append(f"• {w['message']}")
            lines.append("")

        # 成功
        if self.successes:
            lines.append("✅ SUCCESS")
            for s in self.successes:
                lines.append(f"• {s['message']}")
            lines.append("")

        lines.append("💡 SHARE THIS FILE WITH CLAUDE FOR DEBUGGING")
        lines.append("=" * 80)

        report_content = '\n'.join(lines)
        report_path.write_text(report_content, encoding='utf-8')

        self.logger.info(f"Report generated: {report_path}")

        return str(report_path)
