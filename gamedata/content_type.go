package gamedata

import (
	"elichika/dictionary"
	"elichika/utils"



	"xorm.io/xorm"
)

type ContentType struct {
	Id int32 `xorm:"pk"`
	// AmountText string
	IsUnique bool
	// DisplayOrder int32
}

func loadContentType(gamedata *Gamedata, masterdata_db, serverdata_db *xorm.Session, dictionary *dictionary.Dictionary) {
	gamedata.ContentType = make(map[int32]*ContentType)
	err := masterdata_db.Table("m_content_setting").Find(&gamedata.ContentType)
	utils.CheckErr(err)
}

func init() {
	addLoadFunc(loadContentType)
}
