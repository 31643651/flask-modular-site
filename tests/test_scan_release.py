"""
发布包扫描脚本测试（scripts/scan_release.py）

覆盖：禁入文件、真实凭据、本机绝对路径、测试占位口令（INFO）与退出码。
"""

from scripts import scan_release


def _write(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestScanFindings:
    def test_forbidden_files_high(self, tmp_path):
        _write(tmp_path, "Module/json/config.json", "{}")
        _write(tmp_path, "Module/data/app.db", "x")
        _write(tmp_path, "Module/log/app.log", "x")
        _write(tmp_path, "cookies.txt", "x")

        findings = scan_release.scan(tmp_path)
        high = [f for f in findings if f[0] == "HIGH"]
        assert any("禁入文件" in f[1] for f in high)
        assert scan_release.main([str(tmp_path)]) == 1

    def test_absolute_path_high(self, tmp_path):
        _write(tmp_path, "CHANGELOG.md", "路径：D:\\1web app\\开发\\2\\x\n")
        findings = scan_release.scan(tmp_path)
        assert any("本机项目绝对路径" in f[1] for f in findings)

    def test_hardcoded_password_high(self, tmp_path):
        # 动态拼接口令字段名/值，避免本测试源码自身被扫描命中
        field = "pass" + "word"
        fake = "super" + "-secret" + "-value"
        _write(tmp_path, "scripts/x.py", f'{field} = "{fake}"\n')
        findings = scan_release.scan(tmp_path)
        assert any(f[1] == "硬编码口令" for f in findings)

    def test_test_fixture_password_is_info(self, tmp_path):
        _write(tmp_path, "tests/test_a.py", '"password": "pass123",\n')
        findings = scan_release.scan(tmp_path)
        assert findings
        assert all(f[0] == "INFO" for f in findings)
        assert scan_release.main([str(tmp_path)]) == 0

    def test_clean_tree_passes(self, tmp_path):
        _write(tmp_path, "app.py", "print('ok')\n")
        _write(tmp_path, "README.md", "# demo\n")
        assert scan_release.scan(tmp_path) == []
        assert scan_release.main([str(tmp_path)]) == 0
