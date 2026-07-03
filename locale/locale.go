package locale

import (
	"elichika/assetdata"
	"elichika/config"
	"elichika/db"
	"elichika/dictionary"
	"elichika/gamedata"
	"elichika/log"
	"elichika/serverdata"
	"elichika/utils"

	"fmt"
	"strings"
	"time"

	"xorm.io/xorm"
)

// create one engine for each potential file being read
// each locale is free to create and store its own session
var engines = map[string]*xorm.Engine{}

func GetEngine(path string) *xorm.Engine {
	engine, exist := engines[path]
	if exist {
		return engine
	}
	engine, err := xorm.NewEngine("sqlite", path)
	utils.CheckErr(err)
	engines[path] = engine
	return engine
}

type Locale struct {
	Path          string
	Language      string
	StartupKey    []byte
	MasterVersion string
	Gamedata      *gamedata.Gamedata
	Dictionary    *dictionary.Dictionary
}

func (locale *Locale) LoadGamedata(syncChannel chan struct{}) {
	locale.Dictionary = new(dictionary.Dictionary)
	locale.Dictionary.Init(locale.Path, locale.Language)
	locale.Gamedata = new(gamedata.Gamedata)
	masterdataDb, err := db.NewDatabase(locale.Path + "masterdata.db")
	utils.CheckErr(err)
	locale.Gamedata.Init(locale.Language, masterdataDb, serverdata.Database, locale.Dictionary, syncChannel)

}

func (locale *Locale) LoadAsset() {
	AssetdataEngine := GetEngine(fmt.Sprintf("%s/asset_a_%s.db", locale.Path, locale.Language))
	AssetdataEngine.SetMaxOpenConns(50)
	AssetdataEngine.SetMaxIdleConns(10)
	assetdata.Init(locale.Language, AssetdataEngine)

	AssetdataEngine = GetEngine(fmt.Sprintf("%s/asset_i_%s.db", locale.Path, locale.Language))
	AssetdataEngine.SetMaxOpenConns(50)
	AssetdataEngine.SetMaxIdleConns(10)
	assetdata.Init(locale.Language, AssetdataEngine)
}

var (
	Locales map[string](*Locale)
)

func addLocale(path, language, masterVersion, startUpKey string) {
	locale := Locale{
		Path:          path,
		Language:      language,
		MasterVersion: masterVersion,
		StartupKey:    []byte(startUpKey),
	}
	Locales[language] = &locale
}

// localeCandidate is one game-data locale the server can build. init() registers
// only the ones selected in config (config.json "locales"), so a single-region
// user can skip the others and start much faster.
type localeCandidate struct {
	path, language, masterVersion, startupKey string
}

// wantedLocales parses the comma-separated config value into a lower-cased set.
// An empty set means "load everything" (the default / safety fallback).
func wantedLocales() map[string]bool {
	want := map[string]bool{}
	if config.Conf == nil || config.Conf.Locales == nil {
		return want
	}
	for _, part := range strings.Split(*config.Conf.Locales, ",") {
		if l := strings.ToLower(strings.TrimSpace(part)); l != "" {
			want[l] = true
		}
	}
	return want
}

func init() {
	start := time.Now()
	gamedata.GenerateLoadOrder()
	Locales = make(map[string](*Locale))
	syncChannel := make(chan struct{})

	candidates := []localeCandidate{
		{config.JpMasterdataPath, "ja", config.MasterVersionJp, config.JpStartupKey},
		{config.GlMasterdataPath, "en", config.MasterVersionGl, config.GlStartupKey},
		{config.GlMasterdataPath, "zh", config.MasterVersionGl, config.GlStartupKey},
		{config.GlMasterdataPath, "ko", config.MasterVersionGl, config.GlStartupKey},
	}
	want := wantedLocales()
	for _, c := range candidates {
		if len(want) == 0 || want[c.language] {
			addLocale(c.path, c.language, c.masterVersion, c.startupKey)
		}
	}
	// A misconfigured "locales" (blank, or none of the values match a real locale)
	// must not leave the server with zero game data - fall back to all four.
	if len(Locales) == 0 {
		for _, c := range candidates {
			addLocale(c.path, c.language, c.masterVersion, c.startupKey)
		}
	}
	if len(Locales) < len(candidates) {
		loaded := make([]string, 0, len(Locales))
		for lang := range Locales {
			loaded = append(loaded, lang)
		}
		log.Println("Loading game-data locales (config 'locales'): ", strings.Join(loaded, ", "))
	}

	for _, locale := range Locales {
		go locale.LoadGamedata(syncChannel)
	}
	// asset write to the same space so needed to be load manually
	for _, locale := range Locales {
		locale.LoadAsset()
	}
	for i := len(Locales); i > 0; i-- {
		<-syncChannel
	}
	finish := time.Now()
	log.Println("Finished loading databases in: ", finish.Sub(start))
	for language, locale := range Locales {
		gamedata.GamedataByLocale[language] = locale.Gamedata
		// because the order of has map is random, this instance is guaranteed to not
		// be a specific version, so don't depend on it
		gamedata.Instance = locale.Gamedata
	}
}
