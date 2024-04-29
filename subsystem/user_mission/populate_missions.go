package user_mission

import (
	"elichika/enum"
	"elichika/userdata"
)

func populateMissions(session *userdata.Session) {
	for _, mission := range session.Gamedata.MissionByTerm[enum.MissionTermFree] {
		if (mission.StartAt > session.Time.Unix()) || (mission.EndAt < session.Time.Unix()) {
			continue
		}

		userMission := getUserMission(session, mission.Id)
		if userMission.MissionMId != 0 { // valid mission that we can have
			// if not cleared and the mission type has an initializer, call that intialiser again
			// this is correct but it might be slow, so maybe some other check is necessary
			if (!userMission.IsNew) && (!userMission.IsCleared) {
				initializer, exist := missionInitializers[mission.MissionClearConditionType]
				if exist {
					userMission = initializer(session, userMission)
				}
			}
			session.UserModel.UserMissionByMissionId.Set(mission.Id, userMission)
		}
	}
}
