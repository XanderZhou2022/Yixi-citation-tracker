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
   | `DASHBOARD_PASSWORD` | 你设置的网页访问密码，至少 12 个字符 |

   **在 push 本次修改前，先添加 `DASHBOARD_PASSWORD`**：至少 12 个字符，建议使用密码管理器生成 20 位以上随机密码。这就是网页的访问密码。不要写进代码或 `config.json`。

   实际密钥没有复制进此目录。不要将 `api.md` 上传到 GitHub。OpenAlex 密钥可省略，但已建议配置以提高服务额度。
3. **Settings → Actions → General → Workflow permissions** 选择 **Read and write permissions**，保存，使定时任务能将历史数据写回仓库。默认分支须允许 `github-actions[bot]` 直接提交；如果使用分支保护，请为此个人数据仓库调整规则。
4. **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
5. **Actions → Daily citations → Run workflow** 手动运行一次。成功后在该次运行的 `deploy` job 或 **Settings → Pages** 查看网站 URL，通常为 `https://你的用户名.github.io/仓库名/`。

`Checks and Pages` 在 push 时只测试、构建和发布已有数据，不调用收费 API。如果首次 push 发生在启用 Pages 之前，该次发布可能失败；按上述配置后运行 `Daily citations` 即可。Pull request 只运行离线测试，不读取部署密码、不发布。

每日自动任务设为 **香港时间 03:23 / UTC 19:23**。GitHub 的 schedule 可能排队延迟，并非严格准点。定时工作流必须位于默认分支；fork 后要在 Actions 页面启用。公共仓库长期无活动时，GitHub 可能停用定时工作流。

GitHub Pages 公开提供登录页和加密文件；输入正确密码才会解密并展示引用数据。API 密钥仅在 Actions 中用于抓取，不进入网站。你已选择保留现有公开历史，因此旧 Git 提交、旧网站快照或曾下载的数据仍可能被查看；此次加密不能撤回它们。

## 页面功能

- 输入密码解锁；登录成功后用 cookie 记住此浏览器，退出会清除登录。
- 总览显示引用统计与历史趋势；只有一个快照时显示一个点，不补造历史。
- 我的论文与引用详情统一字号、行距和方框页码，每页 10 篇，显示引用数和近15日变化，逐篇折叠，展开查看引用变化曲线，再次点击收起。
- 引用详情选择你的某篇论文后分页显示引用它的论文，每页 10 条；日期与来源图标和标题并排，点击行内空白展开或收起作者单位。
- 引用作者旁标注一个单位，点击引用数字可展开相关论文标题链接。
- 引用论文所属单位与引用作者左右两栏，各自每页 10 行，点击方框数字页码直接跳转；手机上自动上下排列。
- 姓名与四项统计合并为紧凑页头（近7日变化按总引用数与七天前最近快照比较，历史不足七天从最早快照起算），下面直接显示导航。近7日和近15日变化都在历史不足对应天数时从最早记录起算；只有首次快照时为 0。
- OpenAlex / DOI 图标链接和解锁后的 CSV 导出。
- 页面仅显示更新时间，不显示扫描状态、额度横幅或匹配说明文字。

重新打开或刷新浏览器读取已发布快照。需要立即抓取时，运行仓库的 `Daily citations` 工作流。已匹配成功的 OpenAlex 元数据直接复用；未匹配、歧义或暂不可用的记录每七天重试。

## 密码与加密

`DASHBOARD_PASSWORD` 在 Actions 内通过 PBKDF2-SHA256（600,000 次）生成 AES-256-GCM 密钥。每次加密使用新的随机 nonce；Pages 只发布 `data.enc.json`，不发布明文 JSON 或 CSV。CSV 在登录后由浏览器生成。Actions 日志与 Summary 不再列出引用论文及作者单位。

首次运行更新后的 `Daily citations` 时，会将当前 `data/state.json` 转为 `data/state.enc.json`，提交加密文件并删除当前版本的明文文件，保留你已同意公开的旧 Git 历史。**不要手动删除基线。** 本地仍保留旧基线，等待你设置真实密码后由工作流迁移。

登录 cookie 保存派生的解密密钥，不保存原始密码。设置有效期为 400 天，登录会续期；浏览器提前清理、隐私模式、主动退出或更换密码都会要求重输。cookie 也是解密凭证，不应分享。静态 Pages 无法使用服务端 HttpOnly 会话或限制离线密码猜测，所以请用强随机密码；同一 `github.io` 来源下的其他页面应同样可信。

`config.json` 的 `dashboard_salt` 是公开随机盐，不是密码。保持它不变，使每日更新后已有登录继续有效。

更换密码时：

1. 暂时创建 Secret `PREVIOUS_DASHBOARD_PASSWORD`，填旧密码。
2. 将 `DASHBOARD_PASSWORD` 更新为新密码。
3. 手动运行 `Daily citations`，确认成功且仓库已提交新的加密历史。
4. 删除 `PREVIOUS_DASHBOARD_PASSWORD`。浏览器刷新后需要输入新密码。

不要只改密码后删除加密历史；这会丢失追踪记录。新密码不能撤回别人已保存的旧明文或旧密码对应的加密快照。

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

每天先完整抓作者主页；引用数变化时扫描引用详情，每七天复查未变化的列表。未完成的分页在后续更新续抓，并按上次尝试时间轮换目标论文，避免高引用论文一直占用额度。当天额度保存在加密的 `data/state.enc.json`，同日重跑仍受限。6 次/日意味着常规每月最多约 186 次 SerpApi 请求；请按你的账户配额调整。首次本地初始化单独使用了 12 次上限，实际记账 10 次（其中包含本机证书连接失败的保守记账），后续自动任务使用默认 6 次。

首次初始化已经保存真实基线。迁移前推送时保留 `data/state.json`，迁移后保留 `data/state.enc.json`，以后从此基线追踪新增引用。不要删除历史文件来重新跑任务，否则会失去历史并重建基线。更换作者前备份旧数据，再移走当前历史文件；程序会拒绝将不同作者的数据混在一起。可选仓库 Variable `SCHOLAR_URL` 会覆盖 `config.json` 中的 URL。

## 本地使用

需要 Python 3.10+（Actions 使用 3.12），安装 `cryptography` 加密依赖。复制 `.env.example` 为 `.env`，填写 `DASHBOARD_PASSWORD`；需要抓取时再填写 API 密钥。`.env` 不提交。

```bash
# 安装依赖，使用已有快照构建网站，无 API 调用
python3 -m pip install -r requirements.txt
python3 tracker.py --env-file .env --build-only
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

打开 http://127.0.0.1:8765/ 。不要直接双击 HTML，浏览器从 file:// 加载 JSON 可能被限制。

抓取真实数据时执行：

```bash
python3 tracker.py --env-file .env
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
- **Fetch 成功但单位缺失**：后续按规则重试，页面不显示技术匹配说明。OpenAlex 收录缺失或作者单位为空并不意味着没有引用。
- **Persist 步骤失败**：检查工作流写权限和分支保护；不要删除历史文件来修复权限。
- **Deploy 失败**：确认 Pages Source 是 GitHub Actions，且 workflow 的 `github-pages` environment 允许默认分支部署。
- **当天重跑提示额度已用完**：若已有成功快照，任务继续发布该快照，页面不显示额度提示，更新时间保持原值；次日恢复抓取。若没有成功快照，则仍报错。也可根据账户额度提高配置。
- **更新计数后详情待查**：达到请求上限、列表暂空或分页尚未完成；已保存结果保留，后续更新继续。

## 文件布局

```text
.github/workflows/daily.yml  每日抓取、提交历史、部署 Pages
.github/workflows/check.yml  Push/PR 回归测试与 Push 加密发布
config.json                 主页、额度与公开随机盐，无密钥
tracker.py                  抓取、增量追踪、OpenAlex 补全、静态构建
web/                        登录、解密与中文看板 assets
data/state.enc.json         迁移后的加密历史（必须保留）
data/state.json             仅首次迁移前的已公开基线
tests/                      离线行为与加密回归测试
requirements.txt            Python 加密依赖
.env.example                本地密钥格式，无真实密钥
```

## 接口与平台文档

- [SerpApi Google Scholar Author](https://serpapi.com/google-scholar-author-api)
- [SerpApi Google Scholar Cited By](https://serpapi.com/google-scholar-api)
- [OpenAlex API authentication](https://help.openalex.org/api/authentication/)
- [GitHub Pages 自定义 Actions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub schedule 事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

从你的本地 Citation Intelligence 版本改写；数据采集逻辑延续原版本，持久化与部署已迁移至 GitHub。MIT License。
