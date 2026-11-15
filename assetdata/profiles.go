package assetdata

import (
	"fmt"
	"strings"
)

type Region string
type Platform string
type Language string

const (
	RegionGL        Region   = "gl"
	RegionJP        Region   = "jp"
	RegionBoth      Region   = "both"
	PlatformAndroid Platform = "android"
	PlatformIOS     Platform = "ios"
	PlatformBoth    Platform = "both"
	LanguageAll     Language = "all"
	LanguageEN      Language = "en"
	LanguageKO      Language = "ko"
	LanguageZH      Language = "zh"
	LanguageJA      Language = "ja"
)

// AssetProfile identifies one actual source database. It is independent of the
// first locale that registered a shared pack in NameToLocale.
type AssetProfile struct {
	Region   Region
	Platform Platform
	Language Language
}

func (p AssetProfile) String() string {
	return fmt.Sprintf("%s/%s/%s", p.Region, p.Platform, p.Language)
}

// DownloadSelection selects a union of profiles; shared files appear once.
// Empty fields use both regions, both platforms and all languages.
type DownloadSelection struct {
	Region   Region
	Platform Platform
	Language Language
}

func (s DownloadSelection) normalized() DownloadSelection {
	if s.Region == "" {
		s.Region = RegionBoth
	}
	if s.Platform == "" {
		s.Platform = PlatformBoth
	}
	if s.Language == "" {
		s.Language = LanguageAll
	}
	return s
}

func (s DownloadSelection) String() string {
	s = s.normalized()
	return fmt.Sprintf("region=%s platform=%s language=%s", s.Region, s.Platform, s.Language)
}

// Validate rejects impossible combinations instead of silently broadening scope.
func (s DownloadSelection) Validate() error {
	s = s.normalized()
	if s.Region != RegionGL && s.Region != RegionJP && s.Region != RegionBoth {
		return fmt.Errorf("invalid region %q: use gl, jp or both", s.Region)
	}
	if s.Platform != PlatformAndroid && s.Platform != PlatformIOS && s.Platform != PlatformBoth {
		return fmt.Errorf("invalid platform %q: use android, ios or both", s.Platform)
	}
	switch s.Language {
	case LanguageAll, LanguageEN, LanguageKO, LanguageZH, LanguageJA:
	default:
		return fmt.Errorf("invalid language %q: use all, en, ko, zh or ja", s.Language)
	}
	if s.Region == RegionBoth && s.Language != LanguageAll {
		return fmt.Errorf("region both requires language all; choose gl or jp for a specific language")
	}
	if s.Region == RegionGL && s.Language == LanguageJA {
		return fmt.Errorf("region gl has no ja profile: use all, en, ko or zh")
	}
	if s.Region == RegionJP && s.Language != LanguageAll && s.Language != LanguageJA {
		return fmt.Errorf("region jp has only ja: use all or ja")
	}
	return nil
}

// Eight source catalogs fit in one byte per whole file, with no per-profile
// copies of the 200k logical-pack maps. Catalog loading is sequential.
type profileMask uint8

var sourceProfiles = [...]AssetProfile{
	{RegionGL, PlatformAndroid, LanguageEN},
	{RegionGL, PlatformAndroid, LanguageKO},
	{RegionGL, PlatformAndroid, LanguageZH},
	{RegionGL, PlatformIOS, LanguageEN},
	{RegionGL, PlatformIOS, LanguageKO},
	{RegionGL, PlatformIOS, LanguageZH},
	{RegionJP, PlatformAndroid, LanguageJA},
	{RegionJP, PlatformIOS, LanguageJA},
}
var loadedProfiles profileMask
var wholeFileProfiles = map[string]profileMask{}

func (p AssetProfile) mask() (profileMask, error) {
	for i, profile := range sourceProfiles {
		if p == profile {
			return profileMask(1) << i, nil
		}
	}
	return 0, fmt.Errorf("unknown asset profile %s", p)
}

func firstProfileMask(masks []profileMask) profileMask {
	if len(masks) != 0 {
		return masks[0]
	}
	return 0
}

func recordWholeFile(name string, mask profileMask) {
	if mask != 0 {
		previous := wholeFileProfiles[name]
		if previous&mask == 0 {
			wholeFileProfiles[name] = previous | mask
		}
	}
}

// SelectWholeFiles requires every requested source catalog to have been loaded.
// A config-limited or legacy unprofiled load cannot silently become a full download.
func SelectWholeFiles(selection DownloadSelection) (map[string]struct{}, error) {
	if err := selection.Validate(); err != nil {
		return nil, err
	}
	selection = selection.normalized()
	var selected profileMask
	missing := []string{}
	for i, profile := range sourceProfiles {
		if selection.Region != RegionBoth && profile.Region != selection.Region {
			continue
		}
		if selection.Platform != PlatformBoth && profile.Platform != selection.Platform {
			continue
		}
		if selection.Language != LanguageAll && profile.Language != selection.Language {
			continue
		}
		mask := profileMask(1) << i
		selected |= mask
		if loadedProfiles&mask == 0 {
			missing = append(missing, profile.String())
		}
	}
	if len(missing) != 0 {
		return nil, fmt.Errorf("asset profiles not loaded: %s; enable their locales in config and restart", strings.Join(missing, ", "))
	}
	if selected == 0 {
		return nil, fmt.Errorf("no asset profiles match %s", selection)
	}
	names := make(map[string]struct{})
	for name, profiles := range wholeFileProfiles {
		if profiles&selected != 0 {
			names[name] = struct{}{}
		}
	}
	return names, nil
}

// ProfileWholeFileCount is the union of whole files in all loaded profiles.
func ProfileWholeFileCount() int { return len(wholeFileProfiles) }

// AllWholeFiles preserves the historical unfiltered download set, including data
// loaded through Init without profile information.
func AllWholeFiles() map[string]struct{} {
	names := make(map[string]struct{}, len(Metapack))
	for name := range Metapack {
		names[name] = struct{}{}
	}
	for _, pack := range Pack {
		if pack.MetapackName == nil {
			names[pack.PackName] = struct{}{}
		}
	}
	return names
}
