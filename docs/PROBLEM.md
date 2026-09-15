# 问题记录

Mac 上推荐用 Homebrew 安装：

```bash
brew install uv
```

验证：

```bash
uv --version
```

你当前项目要求 Python 3.14，可继续执行：

```bash
cd /Users/dengc4r/dhh_blog/github/trading-cloud
uv python install 3.14
uv sync
uv run pytest
```

如果没有 Homebrew，也可以使用 uv 官方安装脚本：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

官方文档：[uv 安装指南](https://docs.astral.sh/uv/getting-started/installation/)。
