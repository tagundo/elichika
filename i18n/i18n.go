// Package i18n provides the WebUI's interface translations.
//
// The WebUI works in English by default and can switch to Korean ("ko") or
// Japanese ("ja"). English source strings double as the translation keys, so a
// string with no entry simply falls back to its English text – there is never a
// missing-key failure, only an untranslated string.
//
// This is for the WebUI's own chrome (buttons, labels, messages). Game data
// (cards, skills, events, …) is localised separately through the dictionary /
// locale packages and is unaffected by this package.
package i18n

import "strings"

// DefaultLanguage is used whenever no (or an unknown) language is requested.
const DefaultLanguage = "en"

// Language is a selectable UI language for building pickers.
type Language struct {
	Code string
	Name string // native display name
}

// order is the display order of the languages offered in the UI.
var order = []string{"en", "ko", "ja"}

var names = map[string]string{
	"en": "English",
	"ko": "한국어",
	"ja": "日本語",
}

// Languages returns the selectable languages in display order.
func Languages() []Language {
	out := make([]Language, 0, len(order))
	for _, code := range order {
		out = append(out, Language{Code: code, Name: names[code]})
	}
	return out
}

// Supported reports whether code is one of the offered languages.
func Supported(code string) bool {
	_, ok := names[code]
	return ok
}

// Normalize maps a raw code (e.g. "ko-KR", "ja_JP", "EN") to a supported
// language code, falling back to DefaultLanguage when it cannot be matched.
func Normalize(code string) string {
	c := strings.ToLower(strings.TrimSpace(code))
	if c == "" {
		return DefaultLanguage
	}
	c = strings.ReplaceAll(c, "-", "_")
	if i := strings.IndexAny(c, "_."); i >= 0 {
		c = c[:i]
	}
	switch c {
	case "en", "ko", "ja":
		return c
	case "kr", "kor":
		return "ko"
	case "jp", "jpn":
		return "ja"
	case "eng":
		return "en"
	}
	return DefaultLanguage
}

// T translates text into lang. English is both the key and the fallback, so any
// untranslated string is returned unchanged.
func T(lang, text string) string {
	if table, ok := tables[Normalize(lang)]; ok {
		if v, ok := table[text]; ok && v != "" {
			return v
		}
	}
	return text
}

// tables[lang] maps an English source string to its translation.
var tables = map[string]map[string]string{
	"ko": {
		// -- language picker --------------------------------------------
		"Language": "언어",

		// -- navigation / shared ----------------------------------------
		"Return to main menu": "메인 메뉴로 돌아가기",

		// -- admin index (admin_index.go) -------------------------------
		"Config Editor":                   "설정 편집기",
		"Event Selector":                  "이벤트 선택",
		"Event Scheduler":                 "이벤트 예약",
		"Maintenance Mode (for updating)": "점검 모드 (업데이트용)",

		// -- config editor (config_editor.go) ---------------------------
		"Update server runtime config.": "서버 런타임 설정을 변경합니다.",
		"Note that some configurations will be applied right away, some will requires restarting the server.": "일부 설정은 즉시 적용되며, 일부는 서버를 다시 시작해야 적용됩니다.",
		"Finally, you can always delete the config.json to reset everything to default.":                      "언제든 config.json을 삭제하면 모든 설정이 기본값으로 초기화됩니다.",
		"Reset to current config": "현재 설정으로 되돌리기",
		"Update config":           "설정 업데이트",
		"Config updated, some changes will require a server restart to work.": "설정이 업데이트되었습니다. 일부 변경 사항은 서버를 다시 시작해야 적용됩니다.",

		// -- event selector (event_selector.go) -------------------------
		"Select active event": "활성 이벤트 선택",
		"Note that once you click the change event button, the current event (if any) will be ended, the reward will be given out, and the selected event will be started instantly.": "이벤트 변경 버튼을 누르면 현재 이벤트(있는 경우)가 종료되어 보상이 지급되고, 선택한 이벤트가 즉시 시작됩니다.",
		"This happens even if you have selected the same event, so if you are here by mistake, just go back.":                                                                         "같은 이벤트를 선택해도 동일하게 동작하므로, 실수로 들어왔다면 그냥 뒤로 가세요.",
		"Select and start new event": "새 이벤트 선택 및 시작",
		"Event changed!":             "이벤트가 변경되었습니다!",
		"Schedule next event":        "다음 이벤트 예약",
		"Only one event can be scheduled at a time, the scheduled one are displayed":                                "한 번에 하나의 이벤트만 예약할 수 있으며, 예약된 이벤트가 표시됩니다.",
		"If no event is scheduled, then None will be displayed, and the server will automatically choose an event.": "예약된 이벤트가 없으면 None이 표시되며, 서버가 자동으로 이벤트를 선택합니다.",
		"Select and schedule event": "이벤트 선택 및 예약",
		"Event scheduled!":          "이벤트가 예약되었습니다!",

		// -- maintenance mode (maintenance_mode.go) ---------------------
		"Switch the server to maintainence mode so you can update elichika or do other work.":                                                                   "elichika를 업데이트하거나 다른 작업을 할 수 있도록 서버를 점검 모드로 전환합니다.",
		"Note that once you click the button, elichika will shutdown and the admin webui will become temporarily unavailable.":                                  "버튼을 누르면 elichika가 종료되고 관리자 WebUI가 일시적으로 사용 불가가 됩니다.",
		"It might take a while for elichika to fully shut down and for the maintainence server to be up, howerver it shouldn't take longer than a few minutes.": "elichika가 완전히 종료되고 점검 서버가 시작되기까지 시간이 걸릴 수 있으나, 보통 몇 분을 넘지 않습니다.",
		"If it takes too long, then something went wrong and you'll have to restart elichika manually.":                                                         "너무 오래 걸리면 문제가 발생한 것이므로 elichika를 수동으로 다시 시작해야 합니다.",
		"Note that even if you have a clear error message, elichika will still stop.":                                                                           "명확한 오류 메시지가 있더라도 elichika는 그대로 중지됩니다.",
		"Switch to maintainence mode":                            "점검 모드로 전환",
		"No error detected, trying to start maintenance server.": "오류가 감지되지 않았습니다. 점검 서버를 시작합니다.",

		// -- login (login.html / login.go) ------------------------------
		"Admin Password": "관리자 비밀번호",
		"Login":          "로그인",
		"The admin password is stored in config.json, defaulted to an empty string (so just click the login button).": "관리자 비밀번호는 config.json에 저장되며 기본값은 빈 문자열입니다(그냥 로그인 버튼을 누르면 됩니다).",
		"You have pressed Enter key, use submit button instead":                                                       "Enter 키를 눌렀습니다. 대신 제출 버튼을 사용하세요.",
		"Wrong password!": "비밀번호가 틀렸습니다!",
	},
	"ja": {
		// -- language picker --------------------------------------------
		"Language": "言語",

		// -- navigation / shared ----------------------------------------
		"Return to main menu": "メインメニューに戻る",

		// -- admin index ------------------------------------------------
		"Config Editor":                   "設定エディタ",
		"Event Selector":                  "イベント選択",
		"Event Scheduler":                 "イベント予約",
		"Maintenance Mode (for updating)": "メンテナンスモード（更新用）",

		// -- config editor ----------------------------------------------
		"Update server runtime config.": "サーバーのランタイム設定を変更します。",
		"Note that some configurations will be applied right away, some will requires restarting the server.": "一部の設定はすぐに反映され、一部はサーバーの再起動が必要です。",
		"Finally, you can always delete the config.json to reset everything to default.":                      "config.json を削除すれば、いつでもすべての設定を初期値に戻せます。",
		"Reset to current config": "現在の設定に戻す",
		"Update config":           "設定を更新",
		"Config updated, some changes will require a server restart to work.": "設定を更新しました。一部の変更はサーバーの再起動が必要です。",

		// -- event selector ---------------------------------------------
		"Select active event": "アクティブなイベントを選択",
		"Note that once you click the change event button, the current event (if any) will be ended, the reward will be given out, and the selected event will be started instantly.": "イベント変更ボタンを押すと、現在のイベント（あれば）が終了して報酬が配布され、選択したイベントが即座に開始されます。",
		"This happens even if you have selected the same event, so if you are here by mistake, just go back.":                                                                         "同じイベントを選んでも同様に動作するので、誤って開いた場合は戻ってください。",
		"Select and start new event": "新しいイベントを選択して開始",
		"Event changed!":             "イベントを変更しました！",
		"Schedule next event":        "次のイベントを予約",
		"Only one event can be scheduled at a time, the scheduled one are displayed":                                "予約できるイベントは一度に1つだけで、予約中のものが表示されます。",
		"If no event is scheduled, then None will be displayed, and the server will automatically choose an event.": "予約がない場合は None が表示され、サーバーが自動的にイベントを選びます。",
		"Select and schedule event": "イベントを選択して予約",
		"Event scheduled!":          "イベントを予約しました！",

		// -- maintenance mode -------------------------------------------
		"Switch the server to maintainence mode so you can update elichika or do other work.":                                                                   "elichika の更新やその他の作業ができるよう、サーバーをメンテナンスモードに切り替えます。",
		"Note that once you click the button, elichika will shutdown and the admin webui will become temporarily unavailable.":                                  "ボタンを押すと elichika が停止し、管理者 WebUI は一時的に利用できなくなります。",
		"It might take a while for elichika to fully shut down and for the maintainence server to be up, howerver it shouldn't take longer than a few minutes.": "elichika が完全に停止してメンテナンスサーバーが起動するまで時間がかかることがありますが、通常は数分以内です。",
		"If it takes too long, then something went wrong and you'll have to restart elichika manually.":                                                         "時間がかかりすぎる場合は問題が発生しているので、elichika を手動で再起動してください。",
		"Note that even if you have a clear error message, elichika will still stop.":                                                                           "明確なエラーメッセージが出ても、elichika はそのまま停止します。",
		"Switch to maintainence mode":                            "メンテナンスモードに切り替え",
		"No error detected, trying to start maintenance server.": "エラーは検出されませんでした。メンテナンスサーバーを起動します。",

		// -- login ------------------------------------------------------
		"Admin Password": "管理者パスワード",
		"Login":          "ログイン",
		"The admin password is stored in config.json, defaulted to an empty string (so just click the login button).": "管理者パスワードは config.json に保存され、初期値は空文字列です（そのままログインボタンを押してください）。",
		"You have pressed Enter key, use submit button instead":                                                       "Enter キーが押されました。代わりに送信ボタンを使用してください。",
		"Wrong password!": "パスワードが違います！",
	},
}
