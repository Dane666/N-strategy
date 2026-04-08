# -*- coding: utf-8 -*-
"""
代理防护模块。

参考 ma_scanner：在 requests 导入前清理代理环境，避免 macOS 代理干扰行情接口。
"""

import os

PROXY_KEYS = [
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY", "ftp_proxy", "FTP_PROXY",
    "no_proxy", "NO_PROXY",
]


def disable_proxy():
    for key in PROXY_KEYS:
        if key in os.environ:
            del os.environ[key]
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"


def patch_requests_session():
    try:
        import requests

        original_init = requests.Session.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.trust_env = False
            self.proxies = {}

        requests.Session.__init__ = patched_init
    except Exception:
        pass


disable_proxy()
patch_requests_session()
