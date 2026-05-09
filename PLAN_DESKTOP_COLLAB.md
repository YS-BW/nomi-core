# Core / Desktop 协同任务清单

1. Desktop 查看多渠道历史
   - 在 desktop 中查看不同渠道的历史会话
   - 第一优先级是在 desktop 里查看微信聊天记录
   - core 侧配合 `list_sessions / bind_session / load_history`
   - 当前不需要改 `nomi-protocol`

2. Desktop 独立管理模型配置
   - 让 desktop 可以按 provider 维度查看和修改模型配置
   - 至少支持默认 `provider / model / temperature / maxTokens / contextWindowTokens / reasoningEffort / providerRetryMode`
   - provider 分组展示当前配置与可用模型候选
   - core 侧提供远端读写配置接口，并负责热应用到当前 runtime
   - 大概率需要改 `nomi-protocol`

3. Desktop 远端会话管理
   - desktop 需要接入 remote 的完整 session 列表、创建、删除和切换
   - core / protocol 侧已完成：
     - `list_sessions(page_token, page_size, include_archived)`
     - `create_session(session_id?, title?)`
     - `delete_session(session_id)`
     - `session_list / session_created / session_deleted / error.code / error.command`
   - desktop 侧需要完成：
     - 会话管理弹层改成消费 remote 全量视图
     - create / delete / bind / load_history 流程接到新协议
     - `session_not_found / duplicate_session_id / invalid_page_token / session_delete_forbidden` 错误码处理
