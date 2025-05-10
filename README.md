# mastodon2memosAPI

使用python实现转换mastodon的API为memos v0.18.0 的标准API用以适配木木老师的MemosBBS 项目,支持部署在vercel上。

## 介绍

 
实现功能 
访问 `/api/v1/memo` 可返回mastodon的嘟文
访问 `/m/{memoID}`  可跳转到对应的嘟文

## 使用

在vercel上部署
1. fork本项目
2. 导入到vercel

3. 修改Vercel环境变量
   - `MASTODON_BASE_URL`: mastodon的实例地址
   - `MASTODON_ACCOUNT_ID`: 你的mastodon账户ID
   - `MASTODON_ACCESS_TOKEN`: your_access_token 
   - `INSTANCE_TYPE` : mastodon  # 可选值: `mastodon`, `gotosocial`, `pleroma`,默认为`mastodon`
4. 部署完成
