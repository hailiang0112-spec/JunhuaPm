from rest_framework.authentication import SessionAuthentication


class CsrfSessionAuthentication(SessionAuthentication):
    """会话认证 + Django 内置 CSRF 校验（写请求需带 X-CSRFToken）。"""
