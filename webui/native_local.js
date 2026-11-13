// Shared native-local WebUI language and clipboard helpers. No credentials are
// persisted in browser storage; reveal/copy always checks the server again.
const native_local_strings = {
    ko: {
        'Choose a local account': '이 기기의 계정 선택',
        'Select an account stored on this device. No password is needed in this app.': '이 기기에 저장된 계정을 선택하세요. 이 앱에서는 비밀번호 입력이 필요 없습니다.',
        'Filter accounts (optional)': '계정 검색 (선택)',
        'No accounts yet. Create an account in the game client first.': '저장된 계정이 없습니다. 먼저 게임 클라이언트에서 계정을 만드세요.',
        'Client login / migration': '클라이언트 로그인 / 이전',
        'Use this account in another signed game client by entering the same server address, account ID and client login password.': '다른 서명의 게임 클라이언트에서도 같은 서버 주소, 계정 ID, 로그인 비밀번호를 입력하면 이 계정을 사용할 수 있습니다.',
        "Reinstalling a differently signed client may remove that client's local files. Your progress remains on this server. Export a backup first; importing is not needed just to log in.": '서명이 다른 클라이언트를 재설치하면 클라이언트의 로컬 파일이 지워질 수 있습니다. 진행 상황은 이 서버에 남습니다. 먼저 백업을 내보내세요. 로그인만 하려면 계정을 가져올 필요가 없습니다.',
        'Export account backup (.db)': '계정 백업 내보내기 (.db)',
        'Choose another account': '다른 계정 선택',
        'Client server address': '클라이언트에 입력할 서버 주소',
        'Account ID': '계정 ID',
        'Client login password': '클라이언트 로그인 비밀번호',
        'Copy': '복사',
        'Reveal / hide': '표시 / 숨기기',
        'Copy password': '비밀번호 복사',
        'Set / generate client login password': '클라이언트 로그인 비밀번호 설정 / 생성',
        'Existing passwords are stored as bcrypt hashes and cannot be recovered. Only a password explicitly saved here can later be revealed or copied.': '기존 비밀번호는 bcrypt 해시로 저장되어 복구할 수 없습니다. 여기서 명시적으로 저장한 새 비밀번호만 나중에 표시하거나 복사할 수 있습니다.',
        'Changing this password replaces the old game login password. It preserves your account progress, authorization keys and current sessions.': '이 작업은 기존 게임 로그인 비밀번호를 바꿉니다. 계정 진행 상황, 인증 키, 현재 세션은 유지됩니다.',
        'New password (optional; leave blank to generate)': '새 비밀번호 (선택, 비워 두면 자동 생성)',
        'I understand that the old client login password will stop working.': '기존 클라이언트 로그인 비밀번호를 더 이상 사용할 수 없음을 이해했습니다.',
        'Copy connection details': '접속 정보 복사',
        'Server public key (if required by your client)': '서버 공개 키 (클라이언트에서 요구하는 경우)',
        'Copy public key': '공개 키 복사',
        'Include public key in copied connection details': '접속 정보에 공개 키 포함',
        'A current managed password is saved. It stays masked until you reveal or copy it.': '현재 사용할 수 있는 관리 비밀번호가 저장되어 있습니다. 표시하거나 복사할 때까지 숨겨집니다.',
        'No current managed password is available. Explicitly set or generate a new password below.': '표시할 수 있는 현재 관리 비밀번호가 없습니다. 아래에서 새 비밀번호를 직접 설정하거나 생성하세요.',
        'Copied.': '복사했습니다.',
        'Confirm the password change first.': '먼저 비밀번호 변경 확인란을 선택하세요.',
        'Password saved. Reveal or copy it when you are ready to log in.': '비밀번호를 저장했습니다. 로그인할 준비가 되면 표시하거나 복사하세요.',
        'Request failed.': '요청을 처리하지 못했습니다.',
        "0.0.0.0 / :: is a listening address, not a client destination. On this device use the address above. On another device use this server device's LAN address and the same port.": '0.0.0.0 / ::는 서버가 연결을 받는 주소이며 클라이언트 목적지가 아닙니다. 같은 기기에서는 위 주소를 사용하세요. 다른 기기에서는 이 서버 기기의 LAN 주소와 같은 포트를 사용하세요.',
        "On another device, a loopback address points to that device itself. Use this server device's reachable LAN address and port.": '다른 기기에서 루프백 주소는 그 기기 자신을 가리킵니다. 이 서버 기기의 접근 가능한 LAN 주소와 포트를 사용하세요.'
    },
    ja: {
        'Choose a local account': 'この端末のアカウントを選択',
        'Select an account stored on this device. No password is needed in this app.': 'この端末に保存されたアカウントを選択してください。このアプリ内ではパスワード入力は不要です。',
        'Filter accounts (optional)': 'アカウントを絞り込む（任意）',
        'No accounts yet. Create an account in the game client first.': 'アカウントがありません。先にゲームクライアントで作成してください。',
        'Client login / migration': 'クライアントのログイン / 移行',
        'Use this account in another signed game client by entering the same server address, account ID and client login password.': '署名の異なるゲームクライアントでも、同じサーバーアドレス、アカウントID、ログインパスワードでこのアカウントを利用できます。',
        "Reinstalling a differently signed client may remove that client's local files. Your progress remains on this server. Export a backup first; importing is not needed just to log in.": '署名の異なるクライアントを再インストールすると、クライアントのローカルファイルが消えることがあります。進行状況はこのサーバーに残ります。先にバックアップを保存してください。ログインだけならインポートは不要です。',
        'Export account backup (.db)': 'アカウントのバックアップを保存 (.db)',
        'Choose another account': '別のアカウントを選択',
        'Client server address': 'クライアント用サーバーアドレス',
        'Account ID': 'アカウントID',
        'Client login password': 'クライアントのログインパスワード',
        'Copy': 'コピー',
        'Reveal / hide': '表示 / 非表示',
        'Copy password': 'パスワードをコピー',
        'Set / generate client login password': 'ログインパスワードを設定 / 生成',
        'Existing passwords are stored as bcrypt hashes and cannot be recovered. Only a password explicitly saved here can later be revealed or copied.': '既存のパスワードはbcryptハッシュで保存されており復元できません。ここで明示的に保存した新しいパスワードのみ表示・コピーできます。',
        'Changing this password replaces the old game login password. It preserves your account progress, authorization keys and current sessions.': 'この操作で既存のゲームログインパスワードを変更します。進行状況、認証キー、現在のセッションは維持されます。',
        'New password (optional; leave blank to generate)': '新しいパスワード（任意、空欄で自動生成）',
        'I understand that the old client login password will stop working.': '以前のログインパスワードが使えなくなることを理解しました。',
        'Copy connection details': '接続情報をコピー',
        'Server public key (if required by your client)': 'サーバー公開鍵（クライアントで必要な場合）',
        'Copy public key': '公開鍵をコピー',
        'Include public key in copied connection details': '接続情報に公開鍵を含める',
        'A current managed password is saved. It stays masked until you reveal or copy it.': '有効な管理パスワードが保存されています。表示・コピーするまで隠されます。',
        'No current managed password is available. Explicitly set or generate a new password below.': '表示できる有効な管理パスワードがありません。以下で新しく設定・生成してください。',
        'Copied.': 'コピーしました。',
        'Confirm the password change first.': '先にパスワード変更の確認にチェックしてください。',
        'Password saved. Reveal or copy it when you are ready to log in.': 'パスワードを保存しました。ログイン時に表示・コピーしてください。',
        'Request failed.': 'リクエストに失敗しました。',
        "0.0.0.0 / :: is a listening address, not a client destination. On this device use the address above. On another device use this server device's LAN address and the same port.": '0.0.0.0 / :: は待受アドレスで、クライアントの接続先ではありません。同じ端末では上のアドレスを、別の端末ではこのサーバー端末のLANアドレスと同じポートを使ってください。',
        "On another device, a loopback address points to that device itself. Use this server device's reachable LAN address and port.": '別の端末ではループバックアドレスはその端末自身を指します。このサーバー端末の到達可能なLANアドレスとポートを使ってください。'
    }
}
function native_text(text) {
    const lang = (new URLSearchParams(location.search).get('l') || localStorage.getItem('user_locale') || 'en').toLowerCase().split(/[-_]/)[0]
    return (native_local_strings[lang] && native_local_strings[lang][text]) || text
}
function apply_native_language() {
    document.querySelectorAll('[data-native-text]').forEach(function(node) { node.textContent = native_text(node.dataset.nativeText) })
}
async function native_copy_text(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try { await navigator.clipboard.writeText(text); return } catch (_) {}
    }
    const field = document.createElement('textarea')
    field.value = text
    field.style.position = 'fixed'
    field.style.opacity = '0'
    document.body.appendChild(field)
    field.select()
    const copied = document.execCommand('copy')
    field.value = ''
    field.remove()
    if (!copied) throw new Error(native_text('Request failed.'))
}
