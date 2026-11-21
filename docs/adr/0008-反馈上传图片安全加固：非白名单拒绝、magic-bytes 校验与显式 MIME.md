# ADR-0008: 反馈上传图片安全加固：非白名单拒绝、magic-bytes 校验与显式 MIME

- 状态：已接受
- 日期：2026-11-21

## 背景

`/userfix` 反馈提交的图片上传链路存在三层叠加缺陷（探针 `scripts/probe_userfix_image_ct.py` 实测确认）：

1. **非白名单扩展被静默改名而非拒绝**（`userfix.py` save_submission）：上传文件扩展名不在 `ALLOWED_IMAGE_EXTENSIONS`（`.jpg/.jpeg/.png/.gif/.webp/.bmp`）时，代码把文件**改名存为 `.jpg`** 继续保存，而非拒绝该文件。攻击者上传 479KB 的 `.svg`（含 `<script>`）会被存成 `image_1.jpg`。
2. **无内容类型（magic-bytes）校验**：保存路径只看扩展名（被改名后连扩展名检查都绕过了），不校验文件头。任何内容（SVG、HTML、脚本）只要被改名就能入库。
3. **`serve_image` 不指定 mimetype**（`userfix.py` serve 路由）：`send_from_directory` 不传 `mimetype`，依赖 `mimetypes` 猜测——猜的依据正是被篡改后的扩展名 `.jpg`，于是上述 479KB SVG 被以 `Content-Type: image/jpeg` + `X-Content-Type-Options: nosniff` 返回。

**实测结论（潜伏隐患，非活漏洞）**：该 SVG 经 `<img src>` 嵌入、`image/jpeg` 响应头、nosniff、零可执行 payload 的组合下不构成当前可利用的 XSS；但缺陷链完整存在——一旦出现任何「按扩展名猜测 MIME 且被独立窗口打开」的引用路径（浏览器嗅探、后续新页面以 iframe/object 引用、去掉 nosniff 的重构），即升级为存储型 XSS。同理，SVG/HTML 直接入库也让 `/userfix/image/*` 成为内容注入的持久化载体。

约束：
- 反馈提交端对所有登录用户开放（含 100+ 普通用户），上传内容不可信。
- 白名单六种位图格式是用户预期能力，不应缩减（SVG 需求不在 spec `userfix.md` 契约内）。
- 本修复**单独一轮**进行（用户明确要求），不与 UID 分区（ADR-0007）或画廊重写混同。

## 决策

三层修复，纵深防御（任一层单独生效即阻断缺陷链）：

**1. 非白名单扩展直接拒绝**：扩展名不在 `ALLOWED_IMAGE_EXTENSIONS` 的文件**直接拒绝**，不再改名 `.jpg` 保存。校验在**配额扣减之前的路由前置校验**中执行（满足 userfix 契约 #1：校验失败不扣配额），并在 `save_submission` **建目录写盘前**再次校验（纵深防御：失败时无任何文件系统副作用）。同扩展名大小写归一（`.JPG`→`.jpg`，白名单判定不区分大小写）；文件名为空的表单空 part 一律跳过，不计入 6 张上限、不参与校验。

**2. magic-bytes 内容校验**：保存前读取文件头，按扩展名断言真实类型：

| 扩展名 | 接受的 magic-bytes |
|---|---|
| `.jpg`/`.jpeg` | `FF D8 FF` |
| `.png` | `89 50 4E 47 0D 0A 1A 0A` |
| `.gif` | `GIF87a` / `GIF89a` |
| `.bmp` | `BM` |
| `.webp` | `RIFF` + 偏移 8 处 `WEBP` |

内容与扩展名不符（如 SVG/HTML/脚本顶着 `.jpg`）→ 拒绝该文件，不落盘，计入校验失败。实现为独立函数 `_validate_image_bytes(filename, head_bytes)` 便于单测。

**3. `serve_image` 显式 mimetype**：服务路由按**白名单扩展名→固定 MIME 映射**显式传 `mimetype`（`.jpg/.jpeg→image/jpeg`、`.png→image/png`、`.gif→image/gif`、`.webp→image/webp`、`.bmp→image/bmp`），不再依赖 `mimetypes` 猜测；扩展名不在白名单 → **404 拒绝服务**，不返回任何内容；**服务时再做一次内容校验**（读文件头比对扩展名，不符 → 404）——拦截历史上被改名存为 `.jpg` 的非位图脏文件，使「历史脏数据不迁移、靠服务层闭环」成立。保留 `nosniff` 响应头（security.py 已有）作为纵深第二层。

**放弃的备选**：
- ①仅加 magic-bytes、保留改名逻辑——改名行为本身违背"白名单"语义（用户以为在传 .svg 实际存成了 .jpg），且留存改名分支意味着内容校验失败时仍可能有"降级保存"诱惑，弃；
- ②引入 Pillow 做完整解码校验——引入重依赖（编译 wheel、DoS 面反而变大：解码炸弹），magic-bytes 对当前威胁模型（阻断非位图内容入库 + MIME 猜测链）已足够，弃；
- ③serve 改 `send_file` + `as_attachment` 下载头——会破坏 `<img>` 内联预览（userfix.html:173/233 依赖内联渲染），弃。

**历史脏数据**：修复上线前已入库的非白名单文件（若存在）不主动迁移——serve 层 404 已阻断其被服务，安全闭环不依赖数据清洗；30 天保留期自然淘汰。

## 后果

**正面**：缺陷链三层全部切断——非位图内容（SVG/HTML/脚本）无法入库；即便通过带外写入绕过保存层，serve 层按白名单扩展名+显式 MIME 双重拦截不服务；MIME 不再依赖可被篡改历史误导的猜测。userfix 契约 #3（提交 ID 黑名单 + resolve 仍在提交目录内）与本轮互补，上传/服务两端闭合。

**负面/代价**：
- 用户上传损坏/伪造扩展的图片会收到明确拒绝（原先会被静默改名"成功"）——这是预期的行为变更，需在提交端给出清晰错误文案；
- magic-bytes 对极小文件（< 头长）会拒绝——合理，白名单位图格式的最小合法文件远大于 magic 长度；
- 历史脏文件从"可被 `<img>` 引用"变为 404——属收紧，无可用性回归（合法六种格式不受影响）。

**对契约/goldens**：userfix 相关契约若存在图片服务状态码 golden，404 行为变更需先查 `tests/contracts/goldens/userfix_*.json` 再决定是否更新（更新 golden 同样需 ADR，本 ADR 即授权）；`tests/test_userfix_submit_quota.py` 的"图片数量超限不扣配额"路径继续成立（拒绝文件=校验失败不扣配额），不改断言。

**范围外**：UID 分区（ADR-0007）已完成；画廊重写为独立任务。

## 参考

- 探针实测：`scripts/probe_userfix_image_ct.py`（479717 字节 SVG 顶 `.jpg` → `image/jpeg` + nosniff + 零 payload，潜伏隐患定级）
- 缺陷链：`ALLOWED_IMAGE_EXTENSIONS`(userfix.py:46) → 非白名单改名(.jpg, save_submission) → 无 magic-bytes → `serve_image` 靠 `mimetypes` 猜
- 渲染面：`Module/userfix/templates/userfix/userfix.html:173/233`（仅 `<img>` 内联引用）
- 相关契约：`docs/specs/userfix.md` 契约 #1（配额扣减时序）、#3（提交 ID 校验）、#6（图片服务）
