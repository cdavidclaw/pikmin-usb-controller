"""
cx_Freeze 建構腳本 - 將 Python 打包成 macOS App
用法: python3 setup.py build
"""

from cx_Freeze import setup, Executable
import sys

build_exe_options = {
    "packages": [],
    "includes": [],
    "excludes": ["tkinter", "test", "unittest"],
    "build_exe": "dist/PikminUSB",
}

app_exe_options = {
    "exe_version": "1.0.0",
    "copyright": "Copyright 2026",
}

executables = [
    Executable(
        "app.py",
        base=None,  # macOS GUI app (no console)
        target_name="PikminUSB",
        icon=None,
        **app_exe_options
    )
]

setup(
    name="PikminUSB",
    version="1.0.0",
    description="皮克敏 GPS USB 控制工具",
    author="蝦霸",
    options={"build_exe": build_exe_options},
    executables=executables,
)
