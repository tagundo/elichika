package assetdata

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	_ "modernc.org/sqlite"
	"xorm.io/xorm"
)

func resetPackFixture(t testing.TB) {
	t.Helper()
	oldPack, oldMetapack, oldLocale := Pack, Metapack, NameToLocale
	Pack, Metapack, NameToLocale = map[string]*PackType{}, map[string]*MetapackType{}, map[string]string{}
	t.Cleanup(func() { Pack, Metapack, NameToLocale = oldPack, oldMetapack, oldLocale })
}

func packEngine(t testing.TB, path string) *xorm.Engine {
	t.Helper()
	engine, err := xorm.NewEngine("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { engine.Close() })
	return engine
}

func TestStreamingPackLoadKeepsFirstMappingAcrossCatalogs(t *testing.T) {
	resetPackFixture(t)
	engine := packEngine(t, filepath.Join(t.TempDir(), "packs.db"))
	for _, sql := range []string{
		`CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER,category INTEGER)`,
		`INSERT INTO m_asset_package_mapping VALUES('first','shared',100,'meta',12,1),('duplicate','shared',100,NULL,0,2),('free','loose',30,NULL,0,3), (NULL,'null-fields',NULL,NULL,NULL,NULL)`,
	} {
		if _, err := engine.Exec(sql); err != nil {
			t.Fatal(err)
		}
	}
	meta := &MetapackType{MetapackName: "meta", FileSize: 200, Category: 1}
	Metapack["meta"] = meta
	NameToLocale["meta"] = "ko"
	InitPack := func(locale string) { session := engine.NewSession(); defer session.Close(); loadPack(locale, engine) }
	InitPack("ko")
	if len(Pack) != 3 || Pack["shared"].PackageKey != "first" || Pack["shared"].Metapack != meta || Pack["shared"].MetapackOffset != 12 || Pack["loose"].Metapack != nil {
		t.Fatal("streaming changed first-mapping or metapack linking")
	}
	want := DownloadData{Locale: "ko", File: "meta", Start: 12, Size: 100}
	if got := GetDownloadData("shared"); !reflect.DeepEqual(want, got) {
		t.Fatalf("download range changed: got %+v want %+v", got, want)
	}
	if !reflect.DeepEqual(Pack["null-fields"], &PackType{PackName: "null-fields"}) {
		t.Fatal("NULL fields no longer load as the previous zero values")
	}
	first := Pack["shared"]
	InitPack("en")
	if Pack["shared"] != first || NameToLocale["shared"] != "ko" {
		t.Fatal("later locale replaced the first mapping")
	}
}

func TestStreamingPackLoadRetainsCollisionChecks(t *testing.T) {
	for _, kind := range []string{"different size", "metapack name"} {
		t.Run(kind, func(t *testing.T) {
			resetPackFixture(t)
			engine := packEngine(t, filepath.Join(t.TempDir(), "packs.db"))
			if _, err := engine.Exec(`CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER,category INTEGER)`); err != nil {
				t.Fatal(err)
			}
			if _, err := engine.Exec(`INSERT INTO m_asset_package_mapping VALUES('one','shared',100,NULL,0,1)`); err != nil {
				t.Fatal(err)
			}
			if kind == "different size" {
				Pack["shared"] = &PackType{PackName: "shared", FileSize: 99}
			} else {
				Metapack["shared"] = &MetapackType{MetapackName: "shared"}
			}
			defer func() {
				if recover() == nil {
					t.Fatal("unsafe pack collision no longer fails")
				}
			}()
			session := engine.NewSession()
			defer session.Close()
			loadPack("ko", engine)
		})
	}
}

func oldPackSnapshot(t testing.TB, session *xorm.Session) map[string]*PackType {
	t.Helper()
	var rows []*PackType
	if err := session.Table("m_asset_package_mapping").Find(&rows); err != nil {
		t.Fatal(err)
	}
	result := make(map[string]*PackType)
	for _, pack := range rows {
		if _, exists := Metapack[pack.PackName]; exists {
			t.Fatal("stock pack/metapack collision")
		}
		if pack.MetapackName != nil {
			pack.Metapack = Metapack[*pack.MetapackName]
		}
		if prior := result[pack.PackName]; prior == nil {
			result[pack.PackName] = pack
		} else if prior.FileSize != pack.FileSize {
			t.Fatal("stock inconsistent duplicate size")
		}
	}
	return result
}

func TestStockStreamingPacksMatchEveryMapping(t *testing.T) {
	root := os.Getenv("ELICHIKA_STOCK_STARTUP_MASTERDATA")
	if root == "" {
		t.Skip("set ELICHIKA_STOCK_STARTUP_MASTERDATA for initialized stock asset catalogs")
	}
	for _, region := range []string{"gl", "jp"} {
		languages := []string{"en", "ko", "zh"}
		if region == "jp" {
			languages = []string{"ja"}
		}
		for _, language := range languages {
			for _, platform := range []string{"a", "i"} {
				t.Run(fmt.Sprintf("%s/%s/%s", region, language, platform), func(t *testing.T) {
					resetPackFixture(t)
					path := filepath.Join(root, region, "asset_"+platform+"_"+language+".db")
					engine := packEngine(t, "file:"+filepath.ToSlash(path)+"?mode=ro")
					session := engine.NewSession()
					defer session.Close()
					loadMetapack(language, session)
					want := oldPackSnapshot(t, session)
					loadPack(language, engine)
					if !reflect.DeepEqual(want, Pack) {
						t.Fatal("streaming changed stock mapping metadata or first-row selection")
					}
					for name := range Pack {
						if NameToLocale[name] != language {
							t.Fatal("pack locale lost")
						}
					}
					t.Logf("compared %d unique packs", len(Pack))
				})
			}
		}
	}
}

func BenchmarkStockPackCatalog(b *testing.B) {
	root := os.Getenv("ELICHIKA_STOCK_STARTUP_MASTERDATA")
	if root == "" {
		b.Skip("set ELICHIKA_STOCK_STARTUP_MASTERDATA for stock catalog allocation comparison")
	}
	for _, streaming := range []bool{false, true} {
		name := "slice"
		if streaming {
			name = "stream"
		}
		b.Run(name, func(b *testing.B) {
			resetPackFixture(b)
			engine := packEngine(b, "file:"+filepath.ToSlash(filepath.Join(root, "gl", "asset_a_ko.db"))+"?mode=ro")
			session := engine.NewSession()
			defer session.Close()
			loadMetapack("ko", session)
			b.ReportAllocs()
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				Pack, NameToLocale = map[string]*PackType{}, map[string]string{}
				if streaming {
					loadPack("ko", engine)
				} else {
					Pack = oldPackSnapshot(b, session)
					for name := range Pack {
						NameToLocale[name] = "ko"
					}
				}
			}
		})
	}
}
