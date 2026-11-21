"""
发布包导出脚本测试（scripts/export_release.py）

覆盖：排除规则（缓存/运行数据/内部文档/密钥）、包含规则、打包内容与安全扫描。
"""

import zipfile
from pathlib import Path

import pytest

from scripts import export_release as exporter


class TestExcludeRules:
    @pytest.mark.parametrize(
        "rel",
        [
            ".git/config",
            "Module/common/__pycache__/x.cpython-312.pyc",
            "Module/data/app.db",
            "Module/data/app.pid",
            "Module/json/config.json",
            "Module/log/app.log",
            "Module/userfix/submissions/u_2026/a.jpg",
            "Module/static/wallpaper/1.jpg",
            "docs/superpowers/plans/x.md",
            "AGENTS.md",
            "tasks.json",
            "tasks.schema.md",
            "CURRENT_TASK.md",
            "cookies.txt",
            "session.py",
            "可复用开发流程标准与Python移植.md",
            "sdinspector/index.html",
            "imagetest/a.png",
            "待处理文件/gallery.html",
        ],
    )
    def test_excluded(self, rel):
        assert exporter.should_exclude(rel) is True

    @pytest.mark.parametrize(
        "rel",
        [
            "app.py",
            "requirements.txt",
            "LICENSE",
            "README.md",
            "Module/common/settings_utils.py",
            "Module/core/index_service.py",
            "Module/static/common/ui.js",
            "Module/static/gallery/css/gallery.css",
            "docs/modularity.md",
            "docs/adr/0001-壁纸GET接口路径遮蔽与通用错误文案.md",
            "tests/test_export_release.py",
            "scripts/export_release.py",
        ],
    )
    def test_included(self, rel):
        assert exporter.should_exclude(rel) is False


class TestBuildRelease:
    def _fake_repo(self, root: Path):
        files = {
            "app.py": "print('app')\n",
            "requirements.txt": "Flask\n",
            "requirements-dev.txt": "pytest\n",
            "LICENSE": "MIT\n",
            "README.md": "# demo\n",
            "docs/modularity.md": "# modularity\n",
            "docs/superpowers/plans/internal.md": "internal\n",
            "tests/conftest.py": "# conftest\n",
            "Module/data/app.db": "binary\n",
            "Module/json/config.json": "{}\n",
            "Module/log/app.log": "log\n",
            "cookies.txt": "session\n",
            "Module/static/common/ui.js": "// ui\n",
        }
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def test_build_zip_filters_and_scans(self, tmp_path):
        repo = tmp_path / "repo"
        self._fake_repo(repo)
        out = tmp_path / "dist" / "demo.zip"

        result = exporter.build_release(out, name="demo-20260101", root=repo)

        assert result["output"].is_file()
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())

        assert "demo-20260101/app.py" in names
        assert "demo-20260101/Module/static/common/ui.js" in names
        assert "demo-20260101/docs/modularity.md" in names
        # 运行数据/内部文档/密钥均不得入包
        assert all("Module/data/" not in n for n in names)
        assert all("Module/json/" not in n for n in names)
        assert all("docs/superpowers/" not in n for n in names)
        assert all("cookies.txt" not in n for n in names)
        assert all(not n.endswith(".log") for n in names)

    def test_missing_required_file_fails(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("x", encoding="utf-8")
        with pytest.raises(RuntimeError):
            exporter.build_release(tmp_path / "out.zip", root=repo)
