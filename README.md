# mastodon2memosAPI

使用 Python 将 Mastodon / GoToSocial / Pleroma 的状态数据转换为 Memos v0.18.0 可用的 API，并可部署到 Vercel。

## 功能

- 访问 `/api/v1/memo`：返回转换后的 memo 列表
- 访问 `/api/v1/memo/{memo_id}`：返回单条 memo
- 访问 `/m/{memoID}`：跳转到对应原帖
- 访问 `/@{RSS_USERNAME}.rss`：301 重定向到 `/u/1/rss.xml`

## 部署（Vercel）

1. Fork 本仓库
2. 导入到 Vercel
3. 配置环境变量

- `MASTODON_BASE_URL`：实例地址（如 `https://jiong.us`）
- `MASTODON_ACCOUNT_ID`：账号 ID
- `MASTODON_ACCESS_TOKEN`：访问令牌
- `INSTANCE_TYPE`：`mastodon` / `gotosocial` / `pleroma`（默认 `mastodon`）
- `RSS_USERNAME`：RSS 重定向用户名（默认 `sun`）

## RSS 重定向说明

- 当 `RSS_USERNAME=sun` 时，路径 `@sun.rss` 会被重定向到 `/u/1/rss.xml`
- 修改 `RSS_USERNAME` 后，重定向入口会变为对应用户名

## 本地开发

1. 复制 `.env.exm` 为 `.env`
2. 安装依赖：`pip install -r requirements.txt`
3. 运行：`uvicorn api.index:app --reload`

