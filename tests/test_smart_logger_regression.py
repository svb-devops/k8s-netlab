"""
回归测试：SmartLogger 在 root logger 已有 handler 时日志文件仍须创建。

根因：main.py 设置 logging.root.handlers = [JsonFormatter handler] 之后，
SmartLogger._setup_logging() 里的 logging.basicConfig() 因 root 已有 handler
而什么都不做，导致日志文件从不创建。
"""

import logging
from pathlib import Path


def test_smart_logger_generate_report_includes_warnings_section(tmp_path, monkeypatch):
    """
    SmartLogger.generate_report() 在有 warning 时必须包含警告段落（覆盖率回归）。
    """
    monkeypatch.chdir(tmp_path)
    from backend.smart_logger import SmartLogger

    sl = SmartLogger("warn_report_test")
    sl.warning("磁盘空间不足 10%")
    sl.warning("连接超时，已重试")
    report_path = sl.generate_report()

    content = (tmp_path / report_path).read_text(encoding="utf-8")
    assert "磁盘空间不足" in content, (
        "generate_report() 有 warnings 时报告文件内容必须包含警告信息"
    )


def test_smart_logger_creates_log_file_when_root_has_handlers(tmp_path, monkeypatch):
    """
    SmartLogger 在 root logger 已有 handler（即 main.py 已初始化）的情况下，
    仍须写出任务专属日志文件。
    """
    # 模拟 main.py 初始化后的状态：root 已有 handler
    dummy_handler = logging.StreamHandler()
    logging.root.addHandler(dummy_handler)

    # 把日志目录重定向到 tmp_path，不污染真实 logs/
    monkeypatch.chdir(tmp_path)

    try:
        from backend.smart_logger import SmartLogger

        sl = SmartLogger("regression_test")
        sl.info("test message")

        log_file = tmp_path / "logs" / "regression_test.log"
        assert log_file.exists(), (
            "SmartLogger 日志文件未创建 — "
            "basicConfig 在 root 已有 handler 时被跳过导致此回归"
        )
        assert log_file.stat().st_size > 0, "日志文件存在但为空"
    finally:
        logging.root.removeHandler(dummy_handler)


def test_smart_logger_no_duplicate_handlers_on_reuse(tmp_path, monkeypatch):
    """SmartLogger 对同一 task_name 创建两次时不得累积重复 FileHandler（FD 泄漏回归）。"""
    monkeypatch.chdir(tmp_path)
    import logging
    from backend.smart_logger import SmartLogger

    task_name = "create_vm_101_fd_test"

    # 第一次创建
    sl1 = SmartLogger(task_name)
    sl1.info("first instance")

    # 第二次创建（模拟 VM 101 被再次创建的场景）
    sl2 = SmartLogger(task_name)
    sl2.info("second instance")

    logger = logging.getLogger(task_name)
    handler_count = len(logger.handlers)
    assert handler_count == 1, (
        f"Expected exactly 1 FileHandler after creating SmartLogger twice for '{task_name}', "
        f"got {handler_count}. Each extra handler is a leaked file descriptor."
    )

    # 清理
    for h in logger.handlers[:]:
        h.close()
        logger.removeHandler(h)


def test_generate_report_does_not_print_to_stdout(tmp_path, monkeypatch, capsys):
    """generate_report() 不得调用 print()，应通过 logger 输出（结构化日志一致性，N 回归）。"""
    monkeypatch.chdir(tmp_path)
    from backend.smart_logger import SmartLogger

    sl = SmartLogger("test_no_print")
    sl.info("test message")
    sl.generate_report()

    captured = capsys.readouterr()
    assert captured.out == "", (
        "generate_report() called print() — must use logger instead to maintain "
        "structured JSON logging consistency"
    )
