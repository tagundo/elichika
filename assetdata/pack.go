package assetdata

import (
	"elichika/log"
	"elichika/utils"

	"database/sql"
	"fmt"

	"xorm.io/xorm"
)

type PackType struct {
	PackageKey     string        `xorm:"'package_key'"`
	PackName       string        `xorm:"'pack_name'"`
	FileSize       int           `xorm:"'file_size'"`
	MetapackName   *string       `xorm:"'metapack_name'"`
	Metapack       *MetapackType `xorm:"-"`
	MetapackOffset int           `xorm:"'metapack_offset'"`
	Category       int           `xorm:"'category'"`
}

func loadPack(locale string, engine *xorm.Engine) {
	log.Println("Loading Pack")
	// Use a forward SQL cursor rather than xorm.Iterate: Iterate rebuilds its
	// reflection/column schema for every row. These are the same six columns and
	// unordered scan as the previous Find; keep first-mapping/collision rules.
	rows, err := engine.DB().Query("SELECT package_key, pack_name, file_size, metapack_name, metapack_offset, category FROM m_asset_package_mapping")
	utils.CheckErr(err)
	defer rows.Close()
	cnt := 0
	var packageKey, packName, metapackName sql.NullString
	var fileSize, metapackOffset, category sql.NullInt64
	for rows.Next() {
		err = rows.Scan(&packageKey, &packName, &fileSize, &metapackName, &metapackOffset, &category)
		utils.CheckErr(err)
		if _, exists := Metapack[packName.String]; exists {
			log.Panic(fmt.Sprint("same name used for both a pack and a metapack: ", packName.String,
				"\nLocale: ", locale, ", previous locale: ", NameToLocale[packName.String]))
		}
		previous, exists := Pack[packName.String]
		if exists && previous.FileSize == int(fileSize.Int64) {
			continue
		}
		pack := &PackType{
			PackageKey:     packageKey.String,
			PackName:       packName.String,
			FileSize:       int(fileSize.Int64),
			MetapackOffset: int(metapackOffset.Int64),
			Category:       int(category.Int64),
		}
		if metapackName.Valid {
			name := metapackName.String
			pack.MetapackName = &name
			pack.Metapack = Metapack[name]
		}
		if exists {
			log.Panic(fmt.Sprint("pack name reused: ", *previous, *pack))
		}
		Pack[pack.PackName] = pack
		NameToLocale[pack.PackName] = locale
		cnt++
	}
	utils.CheckErr(rows.Err())
	log.Printf("Loaded %d new pack\n", cnt)
}
