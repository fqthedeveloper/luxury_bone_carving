#!/usr/bin/env python3
"""
Generate a cryptographically secure random secret key for Django production deployment.
Usage:
    python generate_secret_key.py
"""
import secrets

if __name__ == '__main__':
    key = secrets.token_urlsafe(50)
    print("=" * 70)
    print("Generated Django Production Secret Key:")
    print("=" * 70)
    print(key)
    print("=" * 70)
    print("Paste this value into your production .env as DJANGO_SECRET_KEY")
