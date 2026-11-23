#!/usr/bin/env python
"""คำสั่งจัดการโปรเจกต์ Django ของระบบ E-Saraban"""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "ไม่พบ Django กรุณาเปิดใช้ virtual environment (.venv) "
            "และติดตั้งด้วย pip install -r requirements-dev.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
