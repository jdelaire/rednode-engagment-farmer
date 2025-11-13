from setuptools import setup, find_packages


setup(
    name="xhs-bot",
    version="0.1.0",
    description="Simple Xiaohongshu engagement CLI (like/comment)",
    packages=find_packages(),
    install_requires=[
        "playwright>=1.45.0",
    ],
    extras_require={
        "web": [
            "fastapi>=0.111.0",
            "uvicorn[standard]>=0.30.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "xhs-bot=xhs_bot.cli:main",
            "xhs-web=xhs_bot.web_server:main",
        ]
    },
    python_requires=">=3.9",
)
