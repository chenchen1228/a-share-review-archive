# A股复盘档案 · GitHub Pages 镜像

[打开复盘网站](https://chenchen1228.github.io/a-share-review-archive/)

源站：https://a-share-review-archive.chen4002812.chatgpt.site

## 免费运行

公开仓库、GitHub Pages 默认域名和标准 ubuntu-latest runner，无付费域名、服务器或额外服务密钥。访客无需登录。

## 自动同步

每 15 分钟由 GitHub Actions 读取 GPT 源站已发布的完整页面和数据，更新图表与历史档案。GitHub 调度和部署可能延迟，不承诺精确到分钟。GPT 云端任务继续生成复盘；这里镜像已公开结果，不重复生成分析。

浏览时使用 GitHub 保存的完整页面和数据，不请求 GPT 数据接口。此仓库不上传私有狼大语料库、取数凭据或作者工程。

## 一致性与归档

核对页面与数据快照的 SHA-256、项目身份、完整状态和历史日期。断源或版本不一致重试三次；仍失败时保留已部署版本，任务报错。缺失历史日期则拒绝覆盖。每次数据修订保存到 docs/history/；首页保留源站历史日期选择。

docs/mirror-manifest.json 记录源数据日期、哈希与归档日期。排除源站注入的、随请求变化的 Cloudflare 挑战脚本，避免相同复盘反复发布；保留报告运行代码与图表。

每轮独立核验实际网站，而非只检查仓库有没有变化。部署失败后，即使仓库已经保存新版，下轮仍补部署。发布后回读 HTML、数据快照与当前内容寻址归档，哈希全部一致才算成功。网络或版本错误会使运行失败，并保留已发布网站；后续轮次重新抓取并核验。

每天的新报告及同日修订均保存完整快照；日期导航来自源站报告数据，旧快照持续保留。GitHub Actions 的运行摘要显示实际发布的数据日期和快照 SHA-256。

## 查看运行状态

[Actions 同步记录](https://github.com/chenchen1228/a-share-review-archive/actions/workflows/sync-pages.yml)。需要立即同步时选择 Run workflow。Settings → Pages 的发布源保持 GitHub Actions。

大陆免代理访问需在具体网络实测。长期无仓库活动时 GitHub 可能暂停定时工作流，可在 Actions 重新启用。源站未更新时，镜像不会自行编造新报告。
