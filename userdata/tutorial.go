package userdata

import (
	"elichika/client"
	"elichika/config"
	"elichika/enum"
	"elichika/utils"
)

// PersistSceneTip records the client's completion marker without changing an
// existing row. The client may repeat a completion after a login migration.
func (session *Session) PersistSceneTip(sceneTipsType int32) {
	_, err := session.Db.Exec(
		"INSERT OR IGNORE INTO u_scene_tips (user_id, scene_tips_type) VALUES (?, ?)",
		session.UserId, sceneTipsType)
	utils.CheckErr(err)
}

// NormalizeTutorialState applies no-tutorial mode to new and existing accounts.
// Call after Login has populated the complete model. Phase99 alone does not
// complete the four first-use guides, including HOME's forced ReferenceBook tip.
func (session *Session) NormalizeTutorialState() {
	if session == nil || session.Db == nil || session.UserStatus == nil ||
		session.SessionType != SessionTypeLogin || session.Finalized || session.IsBasic ||
		config.Conf.Tutorial == nil || *config.Conf.Tutorial {
		return
	}

	session.UserStatus.TutorialPhase = enum.TutorialPhaseTutorialEnd
	if session.UserStatus.TutorialEndAt <= 0 {
		session.UserStatus.TutorialEndAt = session.Time.Unix()
	}
	for _, tip := range []int32{
		enum.SceneTipsTypeLesson,
		enum.SceneTipsTypeReferenceBook,
		enum.SceneTipsTypeMemberGuildSelect,
		enum.SceneTipsTypeMemberGuildCheer,
	} {
		if session.UserModel.UserSceneTipsByEnum.GetOnly(tip) != nil {
			continue
		}
		// Login finalizes only status/authentication. Persist missing markers in
		// its transaction as well as returning them in the first login response.
		session.PersistSceneTip(tip)
		session.UserModel.UserSceneTipsByEnum.Set(tip, client.UserSceneTips{SceneTipsType: tip})
	}
}
