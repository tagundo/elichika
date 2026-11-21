//go:build !embedded

package main

import "testing"

func TestArchiveCLIScopes(t *testing.T) {
	for _, item := range []struct {
		args    []string
		scope   string
		missing bool
	}{
		{nil, "both/both/all", false},
		{[]string{"gl"}, "gl/both/all", false},
		{[]string{"jp", "ios", "ja", "--missing"}, "jp/ios/ja", true},
		{[]string{"gl", "android", "ko", "--missing"}, "gl/android/ko", true},
	} {
		selection, missing, err := archiveScope(item.args)
		got := string(selection.Region) + "/" + string(selection.Platform) + "/" + string(selection.Language)
		if err != nil || got != item.scope || missing != item.missing {
			t.Fatalf("%v: got %s, missing=%t, error=%v", item.args, selection, missing, err)
		}
	}
	for _, args := range [][]string{{"other"}, {"both", "ios", "ja"}, {"--missing", "jp"}, {"gl", "", "all"}} {
		if _, _, err := archiveScope(args); err == nil {
			t.Fatalf("invalid Archive arguments accepted: %v", args)
		}
	}
}
