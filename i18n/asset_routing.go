package i18n

func init() {
	strings := map[string][2]string{
		"Original-game source CDN":          {"원본 게임 파일 CDN", "元のゲームファイルのCDN"},
		"Cache original game files locally": {"원본 게임 파일을 로컬에 캐시", "元のゲームファイルをローカルにキャッシュ"},
		"Original game files use this source CDN or your optional local cache. Added mod files are served automatically by Elichika. Installing content does not change this address.": {"원본 게임 파일은 이 CDN 또는 선택한 로컬 캐시에서 받습니다. 추가한 모드 파일은 Elichika가 자동으로 제공합니다. 콘텐츠를 설치해도 이 주소는 변경되지 않습니다.", "元のゲームファイルはこのCDN、または任意のローカルキャッシュから取得します。追加したMODファイルはElichikaが自動で配信します。コンテンツをインストールしてもこのアドレスは変更されません。"},
		"Use default source CDN": {"기본 원본 CDN 사용", "既定の元データCDNを使用"},
		"This fills the source CDN field. Save with Update config to apply; your current setting stays unchanged until then.":                                                                                                                                                   {"CDN 입력란에 기본 주소를 채웁니다. 적용하려면 설정 업데이트를 누르세요. 저장하기 전까지 현재 설정을 유지합니다.", "CDN欄に既定のアドレスを入力します。「設定を更新」で保存するまで現在の設定は変わりません。"},
		"The source currently points to Elichika itself. Original files must already be local in this mode. If an older installer changed the address, use the default source CDN or enter your previous source, then save. Added mod files work automatically in either mode.": {"현재 원본 CDN이 Elichika 자체를 가리킵니다. 이 모드에서는 원본 파일을 미리 받아 두어야 합니다. 예전 설치 도구가 주소를 바꿨다면 기본 원본 CDN을 사용하거나 이전 주소를 입력한 뒤 저장하세요. 추가한 모드 파일은 어느 모드에서나 자동으로 제공됩니다.", "現在の元データCDNはElichika自身を指しています。このモードでは元ファイルを事前に保存する必要があります。旧インストーラーが変更した場合は既定のCDN、または以前のアドレスを入力して保存してください。追加MODはどちらのモードでも自動配信されます。"},
	}
	for source, values := range strings {
		tables["ko"][source] = values[0]
		tables["ja"][source] = values[1]
	}
}
