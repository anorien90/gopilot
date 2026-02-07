#!/usr/bin/env python3
"""
setup.py - Package installation for gopilot

Install with:
    pip install -e .

Or:
    pip install .
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="gopilot",
    version="0.1.0",
    author="gopilot",
    description="AI-powered LSP server for Neovim using Ollama",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/anorien90/gopilot",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Text Editors :: Integrated Development Environments (IDE)",
    ],
    python_requires=">=3.10",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "gopilot=gopilot.server:main",
        ],
    },
)
