# 高考志愿·反思填报 — 微信小程序(原生)

原生小程序前端,复用现有后端 API(与网页版同一套:`rank_start / rank_next / rank_reorder / rank_chat / rank_end / rank_report`)。

## 目录
- `app.json / app.js / app.wxss` — 全局配置 + 暖纸/赤陶主题
- `utils/api.js` — 后端封装(**改这里的 `BASE` 和 `API_KEY`**)
- `pages/intake` — 填候选 + 确定度 + 价值权重 → 开局
- `pages/game` — 每站场景:top/contender、重排(↑↓)、每轮确定度、追问 chat、下一站
- `pages/ending` — 价值画像 + 排序变化 + 最终确定度
- `pages/report` — 反思报告(轻量 Markdown 渲染)

## 在微信开发者工具里跑
1. 微信开发者工具 → 导入项目 → 目录选 `gaokao/miniprogram/`。
2. AppID:先用「测试号」即可预览;正式发布填你们的 AppID。
3. **`utils/api.js`**:确认 `BASE`(默认 `https://yulai.gaokao.meno.sh`),把 `API_KEY` 填成雨来专用 key。
4. **合法域名**:发布前在 mp.weixin.qq.com → 开发管理 → 服务器域名,把 `BASE` 的域名加入 **request 合法域名**(开发者工具里可临时勾「不校验合法域名」本地测)。

## 测试清单(真机/工具内)
- [ ] intake 填 2+ 候选 → 开始 → 出画像 + 第一站
- [ ] 每站:场景文字、top/contender、来源、确定度滑块都正常
- [ ] ↑↓ 重排后第 1 名变化、后续推演跟着变
- [ ] 追问 chat 能发、有回应、3 轮上限
- [ ] 下一站循环到底 → 结尾画像 + 排序对比
- [ ] 生成报告 → 渲染 + 复制 + 再来一局

## 说明
- 后端 = 网页版同一套(`gaokao/API.md`,yulai 分支)。MP 只是另一个前端。
- 报告用轻量 Markdown 渲染;要更完整可接 `towxml`。
