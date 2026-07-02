"""WSGI entry point for production servers (gunicorn / uwsgi).

Usage:
    gunicorn -w 2 -k gthread --threads 4 -b 0.0.0.0:5002 wsgi:app
    # HTTPS via reverse proxy (nginx + Let's Encrypt),所以这里不再绑 SSL
"""
from app import app

__all__ = ['app']