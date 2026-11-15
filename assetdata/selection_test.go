package assetdata

import (
	"reflect"
	"sort"
	"testing"
)

func TestSelectionUsesWholeFileMembership(t *testing.T) {
	oldLoaded, oldFiles := loadedProfiles, wholeFileProfiles
	t.Cleanup(func() { loadedProfiles, wholeFileProfiles = oldLoaded, oldFiles })
	// Literal catalog fixture: bits 0..5 are GL Android en/ko/zh, iOS en/ko/zh;
	// bits 6..7 are JP Android/iOS ja. These physical objects deliberately overlap.
	loadedProfiles = 0xff
	wholeFileProfiles = map[string]profileMask{
		"common": 0xff, "android-shared": 0x47, "ios-shared": 0xb8,
		"gl-en": 0x09, "gl-ko": 0x12, "jp": 0xc0, "shared-meta": 0xff,
	}
	for _, c := range []struct {
		selection DownloadSelection
		want      []string
	}{
		{DownloadSelection{RegionGL, PlatformAndroid, LanguageEN}, []string{"android-shared", "common", "gl-en", "shared-meta"}},
		{DownloadSelection{RegionGL, PlatformBoth, LanguageEN}, []string{"android-shared", "common", "gl-en", "ios-shared", "shared-meta"}},
		{DownloadSelection{RegionJP, PlatformAndroid, LanguageJA}, []string{"android-shared", "common", "jp", "shared-meta"}},
		{DownloadSelection{RegionBoth, PlatformAndroid, LanguageAll}, []string{"android-shared", "common", "gl-en", "gl-ko", "jp", "shared-meta"}},
		{DownloadSelection{}, []string{"android-shared", "common", "gl-en", "gl-ko", "ios-shared", "jp", "shared-meta"}},
	} {
		names, err := SelectWholeFiles(c.selection)
		if err != nil {
			t.Fatal(err)
		}
		got := []string{}
		for name := range names {
			got = append(got, name)
		}
		sort.Strings(got)
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: got %v want %v", c.selection, got, c.want)
		}
	}
	loadedProfiles &^= 0x08
	if names, err := SelectWholeFiles(DownloadSelection{RegionGL, PlatformBoth, LanguageEN}); err == nil || names != nil {
		t.Fatalf("missing iOS catalog silently broadened selection: %v %v", names, err)
	}
}
