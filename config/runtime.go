package config

import (
	"elichika/enum"
	"elichika/utils"

	"encoding/json"
	"fmt"
	"reflect"
)

type RuntimeConfig struct {
	ServerAddress            *string `json:"server_address" of_label:"Server's address"`
	CdnServer                *string `json:"cdn_server" of_label:"CDN server's address"`
	CdnPathType              *string `json:"cdn_path_type" of_type:"select" of_options:"All\nall\Separated\nseparated" of_label:"CDN path type"`
	CdnPathAll               *string `json:"cdn_path_all" of_label:"CDN path All"`
	CdnPathEN                *string `json:"cdn_path_en" of_label:"CDN path EN"`
	CdnPathKO                *string `json:"cdn_path_ko" of_label:"CDN path KO"`
	CdnPathZH                *string `json:"cdn_path_zh" of_label:"CDN path ZH"`
	CdnPathJA                *string `json:"cdn_path_ja" of_label:"CDN path JA"`
	CdnPartialFileCapability *string `json:"cdn_partial_file_capability" of_type:"select" of_options:"Has static partial file\nstatic_file\nHas partial file mapping\nmapped_file\nHas range API\nhas_range_api\nNothing\nnothing" of_label:"CDN server's partial file capability" `
	AdminPassword            *string `json:"admin_password" of_label:"Admin password" of_type:"password""`
	TapBondGain              *int32  `json:"tap_bond_gain" of_label:"Partner tap bond reward" of_attrs:"min=\"0\" max=\"20000000\"`
	AutoJudgeType            *int32  `json:"auto_judge_type" of_type:"select" of_options:"None\n1\nMiss\n10\nBad\n12\nGood\n14\nGreat\n20\nPerfect\n30" of_label:"Autoplay judge type"`
	Tutorial                 *bool   `json:"tutorial" of_label:"Enable tutorial"`                                                          // whether to turn on tutorial when starting a new account
	LoginBonusSecond         *int32  `json:"login_bonus_second" of_type:"time" of_label:"Login bonus reset time"`                          // the second from mid-night till login bonus
	TimeZone                 *string `json:"timezone" of_label:"Timezone (from tz database)"`                                              // https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
	DefaultContentAmount     *int32  `json:"default_content_amount" of_label:"Default item count" of_attrs:"min=\"0\" max=\"1000000000\""` // the amount of items to give an user if they don't have that item
	MissionMultiplier        *int32  `json:"mission_multiplier" of_label:"Mission progress multiplier" of_attrs:"min=\"0\" max=\"10000\""` // multiply the progress of missions. Only work for do "x" of things, not for "get x different thing or reach x level"
	ResourceConfigType       *string `json:"resource_config_type" of_type:"select" of_options:"Original\noriginal\nComfortable\ncomfortable\nFree\nfree" of_label:"Resource config"`
	LessonDropSkillType      *string `json:"lesson_drop_skill_type" of_type:"select" of_options:"Random\nrandom\Gacha\ngacha\nFixed\nfixed" of_label:"Lesson Drop type"`
}

func defaultConfigs() *RuntimeConfig {
	configs := RuntimeConfig{
		ServerAddress:            new(string),
		CdnServer:                new(string),
		CdnPathType:              new(string),
		CdnPathAll:               new(string),
		CdnPathEN:                new(string),
		CdnPathKO:                new(string),
		CdnPathZH:                new(string),
		CdnPathJA:                new(string),
		CdnPartialFileCapability: new(string),
		AdminPassword:            new(string),
		TapBondGain:              new(int32),
		AutoJudgeType:            new(int32),
		Tutorial:                 new(bool),
		LoginBonusSecond:         new(int32),
		TimeZone:                 new(string),
		DefaultContentAmount:     new(int32),
		MissionMultiplier:        new(int32),
		ResourceConfigType:       new(string),
		LessonDropSkillType:      new(string),
	}
	*configs.ServerAddress = "0.0.0.0:8080"
	*configs.CdnServer = "https://llsifas.catfolk.party/static/"
	*configs.CdnPathType = "separated"
	*configs.CdnPathAll = "assets"
	*configs.CdnPathEN = "2d61e7b4e89961c7"
	*configs.CdnPathKO = "2d61e7b4e89961c7"
	*configs.CdnPathZH = "2d61e7b4e89961c7"
	*configs.CdnPathJA = "b66ec2295e9a00aa"
	*configs.CdnPartialFileCapability = "nothing" // TODO(cdn): Change this to other method when the public cdn is updated
	*configs.AdminPassword = ""
	*configs.TapBondGain = 20
	*configs.AutoJudgeType = enum.JudgeTypePerfect
	*configs.Tutorial = true
	*configs.LoginBonusSecond = enum.HourSecondCount * 4
	*configs.TimeZone = "Asia/Tokyo"
	*configs.DefaultContentAmount = 0
	*configs.MissionMultiplier = 1
	*configs.ResourceConfigType = "original"
	*configs.LessonDropSkillType = "fixed"
	return &configs
}

func Load(p string) *RuntimeConfig {
	if !utils.PathExists(p) {
		c := defaultConfigs()
		c.Save(p)
		return c
	}

	c := RuntimeConfig{}
	err := json.Unmarshal([]byte(utils.ReadAllText(p)), &c)
	if err != nil {
		panic("config file is wrong, change/delete it and try again")
	}
	d := defaultConfigs()
	for i := 0; i < reflect.TypeOf(c).NumField(); i++ {
		f := reflect.ValueOf(&c).Elem().Field(i)
		if f.IsNil() {
			fmt.Println("Use default setting: ", reflect.TypeOf(c).Field(i).Name)
			f.Set(reflect.ValueOf(d).Elem().Field(i))
		}
		fmt.Println(reflect.TypeOf(c).Field(i).Name, ": ", f.Elem())
	}
	return &c
}

func (c *RuntimeConfig) Save(p string) error {
	data, err := json.Marshal(c)
	utils.CheckErr(err)
	utils.WriteAllText(p, string(data))
	return nil
}

var confs = []*RuntimeConfig{}

func UpdateConfig(newConfig *RuntimeConfig) {
	confs = append(confs, Conf)
	newConfig.Save("./config.json") // this has lock so the file can't be corrupted
	// this should be safe because we overwrite the pointer, not the object
	// if someone had an old version of confs then they would just have an access to the old config until they discard it
	// this also assume the pointer size is less than machine word, which it should be
	Conf = newConfig
}

func (r RuntimeConfig) ResourceConfig() *ResourceConfig {
	return resourceConfigs[*r.ResourceConfigType]
}
