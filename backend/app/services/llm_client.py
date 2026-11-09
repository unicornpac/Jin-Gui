# -*- coding: utf-8 -*-
"""统一的 OpenAI 兼容客户端构造。

为什么需要这个模块：

    Windows 上 `urllib.request.getproxies()` 会读取注册表里的系统代理
    （HKCU\\...\\Internet Settings\\ProxyEnable / ProxyServer），但**不解析
    ProxyOverride 绕过列表**。只要用户开着 Clash / V2Ray 之类的工具并把
    「系统代理」打开，httpx（trust_env 默认 True）就会把发往内网服务
    （例如 maas.example.edu.cn → 10.0.0.10）的请求也送进 127.0.0.1:7897。

    表现：CONNECT 隧道能建立（HTTP/1.1 200 Connection established），
    随后 TLS 握手被中断（ConnectionAbortedError 10053），
    openai SDK 抛 `APIConnectionError: Connection error.`，
    业务层只能拿到占位结果。

    因此所有调用内网/自建端点的客户端都必须 trust_env=False。

用法：
    from .llm_client import build_openai_client
    client = build_openai_client(api_key=key, base_url=url, timeout=120)
"""

import httpx


def build_http_client(trust_env: bool = False, timeout: float | None = None) -> httpx.Client:
    kwargs = {"trust_env": trust_env}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return httpx.Client(**kwargs)


def build_openai_client(
    api_key: str,
    base_url: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
):
    """构造不读取系统代理的 OpenAI 兼容客户端。"""
    from openai import OpenAI

    kwargs = {
        "api_key": api_key,
        "http_client": build_http_client(trust_env=False),
    }
    if base_url:
        kwargs["base_url"] = base_url
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return OpenAI(**kwargs)
