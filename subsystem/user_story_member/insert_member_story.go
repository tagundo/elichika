package user_story_member

import (
	"elichika/client"
	"elichika/userdata"
	"elichika/utils"
)

func InsertMemberStory(session *userdata.Session, storyMemberMasterId int32) {
	userStoryMember := client.UserStoryMember{}
	exist, err := session.Db.Table("u_story_member").
		Where("user_id = ? AND story_member_master_id = ?", session.UserId, storyMemberMasterId).Get(&userStoryMember)
	utils.CheckErr(err)
	if !exist {
		session.UserModel.UserStoryMemberById.Set(storyMemberMasterId, client.UserStoryMember{
			StoryMemberMasterId: storyMemberMasterId,
			IsNew:               true,
			AcquiredAt:          session.Time.Unix(),
		})
	}
}
