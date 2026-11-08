package user_scene_tips

import (
	"elichika/userdata"
)

func userSceneTipsFinalizer(session *userdata.Session) {
	for _, userSceneTips := range session.UserModel.UserSceneTipsByEnum.Map {
		session.PersistSceneTip(userSceneTips.SceneTipsType)
	}
}

func init() {
	userdata.AddFinalizer(userSceneTipsFinalizer)
}
