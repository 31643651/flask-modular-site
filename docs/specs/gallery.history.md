# gallery.history

[2026-11-13] 初始化：从 architecture.md 提炼意图锚点，锚定本次修复后的行为契约。

[2026-11-21] ADR-0009 结构重写（行为不变）：删除零引用死副本 gallery.html（移入待处理文件）；index.html 的 CSS/JS 提取为全局静态资产 gallery.css/gallery-page.js（注入三行内联保留，滑动原地换图 6 点语义锚定保留）；favorites.css 外置、两页灯箱 markup 参数化 include；三蓝图 gallery_enabled 守卫统一、路径工具下沉 gallery_service。契约（本文件 gallery.md）与两份 golden 零改动，全量 528 passed / 0 failed。
