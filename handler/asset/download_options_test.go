package asset

import (
	"elichika/assetdata"
	"elichika/config"
	"reflect"
	"testing"
)

func TestParseDownloadOptionsPreservesLegacyAndScopes(t *testing.T) {
	for _, c := range []struct {
		args      []string
		workers   int
		scoped    bool
		selection assetdata.DownloadSelection
	}{
		{nil, 8, false, assetdata.DownloadSelection{assetdata.RegionBoth, assetdata.PlatformBoth, assetdata.LanguageAll}},
		{[]string{"4"}, 4, false, assetdata.DownloadSelection{assetdata.RegionBoth, assetdata.PlatformBoth, assetdata.LanguageAll}},
		{[]string{"4", "--region", "gl", "--platform", "android", "--language", "ko"}, 4, true, assetdata.DownloadSelection{assetdata.RegionGL, assetdata.PlatformAndroid, assetdata.LanguageKO}},
		{[]string{"--region=jp", "--platform=ios", "--language=ja"}, 8, true, assetdata.DownloadSelection{assetdata.RegionJP, assetdata.PlatformIOS, assetdata.LanguageJA}},
		{[]string{"--region", "both"}, 8, true, assetdata.DownloadSelection{assetdata.RegionBoth, assetdata.PlatformBoth, assetdata.LanguageAll}},
	} {
		got, err := ParseDownloadOptions(c.args)
		if err != nil || got.Workers != c.workers || got.Scoped != c.scoped || !reflect.DeepEqual(got.Selection, c.selection) {
			t.Errorf("%v: got %+v %v", c.args, got, err)
		}
	}
}

func TestParseDownloadOptionsRejectsBadArguments(t *testing.T) {
	for _, args := range [][]string{
		{"0"}, {"-1"}, {"not-a-worker"}, {"--region", "xx"}, {"--platform", "a"},
		{"--language", "de"}, {"--region", "gl", "--language", "ja"},
		{"--region", "jp", "--language", "en"}, {"--region", "both", "--language", "ko"},
		{"--region="}, {"--language="}, {"--platform="}, {"--region"}, {"--unknown", "gl"},
		{"8", "2"}, {"--region", "gl", "4"},
	} {
		if _, err := ParseDownloadOptions(args); err == nil {
			t.Errorf("invalid args accepted: %v", args)
		}
	}
}

func TestDownloadMissingRejectsScopeBeforeReadingCDNConfig(t *testing.T) {
	// An invalid selection must fail before reading CDN configuration or starting workers.
	previous := config.Conf
	config.Conf = nil
	t.Cleanup(func() { config.Conf = previous })
	if err := DownloadMissing(2, assetdata.DownloadSelection{Region: assetdata.Region("bad")}); err == nil {
		t.Fatal("invalid selection accepted")
	}
}
