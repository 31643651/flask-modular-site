// 全站公共 UI 脚本（classic script，非 module）
// 收敛原先在多个模板中重复定义的 Cookie / CSRF / 对话框 / 暗夜模式逻辑。
// 注意：confirmDialog 必须先捕获 dialogCallback 再 closeDialog()，
// 否则 closeDialog 会把回调置空，确认动作永不执行（ADR-0006 根因 A）。

var dialogCallback = null;

// 获取 Cookie；不存在时返回空字符串
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

// 获取 CSRF Token：优先模板注入的 window.csrfToken，回退 cookie
function getCsrfToken() {
    if (window.csrfToken) return window.csrfToken;
    return getCookie('csrf_token');
}

// 显示自定义对话框
function showDialog(message, callback, showCancel = true) {
    document.getElementById('dialogMessage').textContent = message;
    document.getElementById('dialogModal').style.display = 'flex';
    document.getElementById('dialogCancel').style.display = showCancel ? 'block' : 'none';
    dialogCallback = callback;
}

// 确认：先捕获回调，再关闭（关闭会置空 dialogCallback），最后触发回调
function confirmDialog() {
    var cb = dialogCallback;
    closeDialog();
    if (cb) cb(true);
}

// 关闭自定义对话框
function closeDialog() {
    document.getElementById('dialogModal').style.display = 'none';
    dialogCallback = null;
}

// 替换 alert
function showAlert(message) {
    showDialog(message, null, false);
}

// 替换 confirm
function showConfirm(message, callback) {
    showDialog(message, callback, true);
}

// 依据 darkMode Cookie 应用暗夜模式
function applyDarkModeFromCookie() {
    if (getCookie('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
    } else {
        document.body.classList.remove('dark-mode');
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyDarkModeFromCookie);
} else {
    applyDarkModeFromCookie();
}
