# Citation Intelligence

追踪 Yixi Zhou 的 Google Scholar 引用变化，并查看引用论文题目、作者，以及作者在该篇论文中记录的单位。Python 抓取器 + GitHub Actions 每日任务 + GitHub Pages 静态看板，无服务器、无 Hugging Face 依赖。

主页已配置在 `config.json`：https://scholar.google.com/citations?user=3oc8NLcAAAAJ&hl=en

## Push 后的部署步骤

1. 将此目录的所有源文件和 `data/state.json` 推送到 GitHub 仓库的默认分支（推荐 `main`）。不要只上传 `web/`。`.github/` 目录必须一起上传。
2. 仓库 **Settings → Secrets and variables → Actions → New repository secret** 添加：

   | Secret 名称 | 值 |
   | --- | --- |
   | `SERPAPI_KEY` | 你原 `api.md` 的 SerpApi 密钥 |
   | `OPENALEX_API_KEY` | 你原 `api.md` 的 OpenAlex 密钥 |

   实际密钥没有复制进此目录。不要将 `api.md` 上传到 GitHub。OpenAlex 密钥可省略，但已建议配置以提高服务额度。
3. **Settings → Actions → General → Workflow permissions** 选择 **Read and write permissions**，保存，使定时任务能将历史数据写回仓库。默认分支须允许 `github-actions[bot]` 直接提交；如果使用分支保护，请为此个人数据仓库调整规则。
4. **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
5. **Actions → Daily citations → Run workflow** 手动运行一次。成功后在该次运行的 `deploy` job 或 **Settings → Pages** 查看网站 URL，通常为 `https://你的用户名.github.io/仓库名/`。

`Checks and Pages` 在 push 时只测试、构建和发布已有数据，不调用收费 API。如果首次 push 发生在启用 Pages 之前，该次发布可能失败；按上述配置后运行 `Daily citations` 即可。Pull request 只测试与构建，不发布。

每日自动任务设为 **香港时间 03:23 / UTC 19:23**。GitHub 的 schedule 可能排队延迟，并非严格准点。定时工作流必须位于默认分支；fork 后要在 Actions 页面启用。公共仓库长期无活动时，GitHub 可能停用定时工作流。

GitHub Pages 看板和 JSON/CSV 数据会公开；API 密钥仅在 Actions 的环境变量中使用。私有仓库使用 Pages 的可用性取决于 GitHub 账户方案。

## 页面功能

- 总引用数、相对前一个已记录日期的净变化、每篇论文引用数与扫描状态。
- 每日历史曲线；只有首次快照时显示该日期引用数，不补造过去数据。
- 引用详情：引用论文题目、论文链接、发现时间、它引用了你的哪篇论文、作者与作者对应单位。
- 按目标论文、首次导入/后续新发现筛选，按题目、作者或单位搜索。
- 引用作者、引用单位汇总；单位按不同引用论文去重。
- 导出 UTF-8 BOM CSV，包含作者与单位的对应 JSON，适合 Excel 打开。
- Actions 每次运行的 Summary 显示当日新发现的引用论文及作者单位。

“刷新页面”读取已发布快照。需要立即抓取时，运行仓库的 `Daily citations` 工作流。

## 数据口径

总引用数与具体引用列表来自 SerpApi 的 Google Scholar 接口。每篇目标论文首次完整扫描的结果标为基线，后续未见过的引用关系才标为新发现。新加入主页的目标论文也单独建立基线。

引用列表的发现时间不是引用实际发生时间。“当日净增 1”和“发现一篇新引用论文”分别展示，因为 Scholar 的计数与列表可能不同步，旧论文可能补录，引用也可能移除。

OpenAlex 提供**该篇引用论文的作者单位**，不代表作者当前单位。自动匹配采用 DOI + 完整标准化题目，或完整标准化题目 + 作者姓氏 + 可用年份。多个候选吻合时保留为歧义，不自动选择单位；未匹配时展示 Scholar 作者原文。即使匹配成功，来源中的作者或单位也可能错误，页面提供 OpenAlex 和 DOI 链接供核验。已有匹配记录不会每天重新抓取；未匹配/歧义/暂不可用的元数据每七天重试。

引用论文按标准化题目去重：同题不同论文可能合并，题目显著改动可能重复。某篇引用论文引用你的多篇论文时，保存多个引用关系，但论文与单位汇总只按一篇计数。历史记录保留，不自动删除已消失的引用。

## 请求额度与续抓

`config.json` 可调整以下参数：

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `scholar_url` | 已配置你的主页 | 更换追踪作者 |
| `timezone` | `Asia/Hong_Kong` | 快照日期与发现时间 |
| `max_serp_requests_per_day` | 6 | 作者主页与 Cited By 合计请求上限 |
| `max_openalex_requests_per_day` | 40 | 作者单位补全请求上限 |
| `max_cited_pages_per_paper` | 2 | 每篇论文每次扫描最多页数，每页 10 条 |
| `reconcile_days` | 7 | 引用数不变时定期复查间隔 |

每天先完整抓作者主页；引用数变化时扫描引用详情，每七天复查未变化的列表。未完成的分页在后续更新续抓，并按上次尝试时间轮换目标论文，避免高引用论文一直占用额度。当天额度保存在 `data/state.json`，同日重跑仍受限。6 次/日意味着常规每月最多约 186 次 SerpApi 请求；请按你的账户配额调整。首次本地初始化单独使用了 12 次上限，实际记账 10 次（其中包含本机证书连接失败的保守记账），后续自动任务使用默认 6 次。

首次初始化已经保存真实基线。推送时保留 `data/state.json`，以后就从此基线追踪新增引用。不要删除此文件来重新跑任务，否则会失去历史并重建基线。更换作者前备份旧数据，再移走 `data/state.json`；程序会拒绝将不同作者的数据混在一起。可选仓库 Variable `SCHOLAR_URL` 会覆盖 `config.json` 中的 URL。

## 本地使用

需要 Python 3.10+（Actions 使用 3.12），不需要第三方 Python 库。

```bash
# 使用已有快照构建网站，无 API 调用
python3 tracker.py --build-only
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

打开 http://127.0.0.1:8765/ 。不要直接双击 HTML，浏览器从 file:// 加载 JSON 可能被限制。

抓取真实数据时，复制 `.env.example` 为 `.env`，填写两个密钥，然后执行：

```bash
python3 tracker.py --env-file .env
```

也可以直接使用原密钥文件：

```bash
python3 tracker.py --env-file /Users/zhou/Downloads/citation-intelligence/api.md
```

此机器的 Python 默认 CA 文件缺失，本地验证采用系统可信证书。若出现证书连接失败，使用：

```bash
SSL_CERT_FILE=/etc/ssl/cert.pem python3 tracker.py --env-file .env
```

Ubuntu Actions runner 无需此设置。程序不输出密钥或包含密钥的请求 URL，`.env`、`api.md`、生成的 `site/` 和 Python 缓存已加入 `.gitignore`。

## 检验与故障处理

```bash
python3 -m unittest discover -s tests -v
```

回归测试覆盖基线/新增去重、跨日变化、同日重跑、分页续抓、额度轮换、扫描中引用数变化、元数据匹配与歧义、失败时保留数据和额度、CSV 防公式及静态产物不泄露密钥。真实数据验证结果见 `VERIFICATION.md`。

- **工作流 Fetch 失败**：检查 Secrets、Scholar URL 和额度。已有历史保留；已消耗的额度会提交回仓库；失败会显示在 Actions。
- **Fetch 成功但单位缺失**：页面显示匹配状态，后续按规则重试。OpenAlex 收录缺失或作者单位为空并不意味着没有引用。
- **Persist 步骤失败**：检查工作流写权限和分支保护；不要删除历史文件来修复权限。
- **Deploy 失败**：确认 Pages Source 是 GitHub Actions，且 workflow 的 `github-pages` environment 允许默认分支部署。
- **当天重跑提示额度已用完**：若已有成功快照，任务继续发布该快照，页面提示本次未刷新数据；次日恢复抓取。若没有成功快照，则仍报错。也可根据账户额度提高配置。
- **更新计数后详情待查**：达到请求上限、列表暂空或分页尚未完成；已保存结果保留，后续更新继续。

## 文件布局

```text
.github/workflows/daily.yml  每日抓取、提交历史、部署 Pages
.github/workflows/check.yml  Push/PR 回归测试与 Push 发布
config.json                 主页与额度配置，无密钥
tracker.py                  抓取、增量追踪、OpenAlex 补全、静态构建
web/index.html              中文静态看板
data/state.json            持久历史与已导入基线（必须提交）
tests/test_tracker.py       离线行为回归测试
.env.example                本地密钥格式，无真实密钥
```

## 接口与平台文档

- [SerpApi Google Scholar Author](https://serpapi.com/google-scholar-author-api)
- [SerpApi Google Scholar Cited By](https://serpapi.com/google-scholar-api)
- [OpenAlex API authentication](https://help.openalex.org/api/authentication/)
- [GitHub Pages 自定义 Actions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub schedule 事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

从你的本地 Citation Intelligence 版本改写；数据采集逻辑延续原版本，持久化与部署已迁移至 GitHub。MIT License。
