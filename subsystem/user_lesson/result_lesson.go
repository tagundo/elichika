package user_lesson

import (
	"elichika/client/response"
	"elichika/enum"
	"elichika/generic/drop"
	"elichika/log"
	"elichika/subsystem/user_lesson_deck"
	"elichika/userdata"
	"elichika/utils"
)

func ResultLesson(session *userdata.Session) response.LessonResultResponse {
	resp := response.LessonResultResponse{}
	exists, err := session.Db.Table("u_lesson").Where("user_id = ?", session.UserId).Get(&resp)
	utils.CheckErrMustExist(err, exists)

	// An older APK may have persisted an empty first result before the execute fix.
	// Its recipe was never stored. Recover only with a skill available to every recipe,
	// and persist it once so reconnects cannot reroll or duplicate the award.
	if resp.DropSkillList.Size() == 0 && session.UserStatus.LessonResumeStatus == enum.TopPriorityProcessStatusLesson &&
		lessonSkillGuideIncomplete(session) {
		var pool *drop.WeightedDropList[int32]
		if session.Gamedata.Lesson != nil {
			pool = session.Gamedata.Lesson.FirstSkillLegacyDrop
		}
		deck := user_lesson_deck.GetUserLessonDeck(session, resp.SelectedDeckId)
		skill := firstLessonCompatibilitySkill(session, deck, pool)
		resp.DropSkillList.Append(skill)
		affected, err := session.Db.Table("u_lesson").Where("user_id = ?", session.UserId).
			Cols("drop_skill_list").Update(&resp)
		utils.CheckErr(err)
		if affected != 1 {
			log.Panic("first lesson skill guide could not update its existing pending result")
		}
		log.Printf("INFO: first lesson skill guide compatibility: legacy result user=%d skill=%d position=%d",
			session.UserId, skill.PassiveSkillId, skill.Position)
	}

	resp.UserModelDiff = &session.UserModel
	return resp
}
