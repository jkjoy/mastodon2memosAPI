# mastodon2memosAPI

转换mastodon的API为memos v0.18.0 的标准API用以适配木木老师的MemosBBS 项目

## 介绍

```
id=int(mastodon_post['id']), # mastodon的嘟文ID
creatorId=1,  # 强制设置为1
creatorName=account['display_name'], # mastodon的显示名称
creatorUsername=account['username'], # mastodon的用户名
createdTs=created_ts, # mastodon的嘟文创建时间戳
updatedTs=created_ts, # mastodon的嘟文更新时间戳
displayTs=created_ts, # mastodon的嘟文显示时间戳
content=content, # mastodon的嘟文内容
resourceList=resource_list, # mastodon的嘟文资源列表
relationList=[], # 关系列表
visibility="PUBLIC" if mastodon_post['visibility'] == 'public' else "PRIVATE", # 嘟文的可见性
pinned=mastodon_post.get('pinned', False), # 是否置顶
rowStatus="NORMAL" # 嘟文的状态
```

实现功能 
访问 /api/v1/memo 可返回mastodon的嘟文
访问 /m/{memoID}  可跳转到对应的嘟文

## 使用

在vercel上部署
1. fork本项目
2. 导入到vercel

3. 修改Vercel环境变量
   - `MASTODON_BASE_URL`: mastodon的实例地址
   - `MASTODON_ACCOUNT_ID`: 你的mastodon账户ID
   - `MASTODON_ACCESS_TOKEN`: your_access_token (Gotosocial必须)
   - `INSTANCE_TYPE` : mastodon  # 可选值: `mastodon`, `gotosocial`, `pleroma`,默认为`mastodon`
4. 部署完成
