"""Vercel 函数入口 —— /api/preview

Vercel 的 /api 目录约定：一个 .py 文件就是一个路由。
所以每个接口都得有个自己的文件 —— 这是平台的规矩，绕不开。
真正的实现在 server.py 里，这里只做一件事：把路由"钉死"再转交。
钉死很重要 —— 平台不保证把原始 PATH_INFO 传进来，靠它分发会翻车。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import make_app  # noqa: E402

app = make_app("/api/preview")
