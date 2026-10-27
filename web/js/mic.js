/* 麦克风可用性检测 —— 跟读功能的第一道门。
 *
 * 为什么要有这个文件:
 *   浏览器只在**安全上下文**里给麦克风(HTTPS,或 http://localhost)。
 *   在 http://192.168.x.x:5002 这种局域网地址下,navigator.mediaDevices
 *   整个是 undefined,getUserMedia 直接抛 TypeError。
 *   以前页面只留一句「无法访问麦克风」,家长和孩子完全看不出原因,
 *   表现就是「点了没反应」。现在把原因和下一步都讲清楚。
 *
 * 用法:
 *   const st = MicGuard.status();
 *   if (!st.ok) { el.textContent = st.message; return; }
 *   ...catch 里:el.textContent = MicGuard.describeError(err);
 */
(function (global) {
    'use strict';

    function host() {
        return global.location ? global.location.host : '(未知地址)';
    }

    function localhostHint() {
        // 端口从当前地址里借一下,免得写死 5002(测试实例是 5003)
        const port = (global.location && global.location.port) || '5002';
        return `在本机浏览器打开 http://localhost:${port} 也可以用。`;
    }

    function status() {
        if (global.isSecureContext === false) {
            return {
                ok: false,
                code: 'insecure',
                message: `当前地址 ${host()} 不是 HTTPS,浏览器不给麦克风。`
                    + `${localhostHint()}`,
                detail: 'isSecureContext=false → navigator.mediaDevices 不可用',
            };
        }
        if (!global.navigator || !navigator.mediaDevices
            || !navigator.mediaDevices.getUserMedia) {
            return {
                ok: false,
                code: 'unsupported',
                message: '这个浏览器不支持录音(MediaRecorder)。'
                    + '请换 Chrome / Edge / Safari 的较新版本。',
                detail: 'navigator.mediaDevices.getUserMedia 缺失',
            };
        }
        if (typeof global.MediaRecorder === 'undefined') {
            return {
                ok: false,
                code: 'no-recorder',
                message: '这个浏览器不支持录音(MediaRecorder)。'
                    + '请换 Chrome / Edge / Safari 的较新版本。',
                detail: 'MediaRecorder 缺失',
            };
        }
        return { ok: true, code: 'ok', message: '', detail: '' };
    }

    function describeError(err) {
        const name = (err && err.name) || '';
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
            return '麦克风权限被拒了。在浏览器地址栏的权限图标里允许麦克风,再读一次。';
        }
        if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
            return '没找到麦克风设备。检查一下耳机/麦克风接好了没。';
        }
        if (name === 'NotReadableError' || name === 'TrackStartError') {
            return '麦克风被别的程序占用了(比如视频会议),关掉再试。';
        }
        if (name === 'SecurityError') {
            return `浏览器不让这个页面用麦克风。${localhostHint()}`;
        }
        if (name === 'TypeError') {
            // 非安全上下文下最典型的表现
            return `这个地址拿不到麦克风。${localhostHint()}`;
        }
        return '打不开麦克风:' + ((err && err.message) || String(err));
    }

    global.MicGuard = { status: status, describeError: describeError };
}(window));
