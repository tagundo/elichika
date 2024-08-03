package user_lesson

import (
	"elichika/client"
	"elichika/client/request"
	"elichika/client/response"
	"elichika/config"
	"elichika/enum"
	"elichika/generic"
	"elichika/generic/drop"
	"elichika/item"
	"elichika/subsystem/user_content"
	"elichika/subsystem/user_lesson_deck"
	"elichika/subsystem/user_member_guild"
	"elichika/subsystem/user_mission"
	"elichika/subsystem/user_status"
	"elichika/subsystem/user_subscription_status"
	"elichika/userdata"
	"math/rand"
	"time"
	"reflect"
	"sort"
    "encoding/json"
    "io/ioutil"
    "log"
    "strconv"
)

type SkillData struct {
    Positions map[string][]int32 `json:"positions"`
}

// handle the lesson and write the result to the database
// drop is calculated using the following process:
// - First iterate over the lesson menu in the order sent, let's say A, B, C, and get a random drop count for each of them
// - Then generate the items using a generic.random list.
//   - We pick the list based on whether the user has the training enhancing items requested
//
// - Finally there is a chance to add megaphones, if it's applicable.
// - For 3 times, the order of A B C is not preserved for the later runs, instead it's sorted
//   - Don't really know why this is the case
//   - One plausible theory is that they sorted the list to use it for insight skills as the order doesn't matter
//
// - the amount of drop is assumed to be the following per instace of lesson (9 in total for x3), start with 15 and go up to 25
//   - 0.25
//   - 0.08
//   - 0.08
//   - 0.25
//   - 0.08
//   - 0.08
//   - 0.11
//   - 0.01
//   - 0.01
//   - 0.03
//   - 0.01
//   - 0.01
//
// - the amount of megaphone drop is assumed to be the following per instance of lesson menu, starting with 0, end with 3
//   - 0.81
//   - 0.1
//   - 0.075
//   - 0.015
//
// TODO(hard_coded): Maybe this should be in the database
var (
	dropCountList          drop.WeightedDropList[int32]
	megaphoneDropCountList drop.WeightedDropList[int32]
)

func init() {
	dropCountList.AddItem(15, 25)
	dropCountList.AddItem(16, 8)
	dropCountList.AddItem(17, 8)
	dropCountList.AddItem(18, 25)
	dropCountList.AddItem(19, 8)
	dropCountList.AddItem(20, 8)
	dropCountList.AddItem(21, 11)
	dropCountList.AddItem(22, 1)
	dropCountList.AddItem(23, 1)
	dropCountList.AddItem(24, 3)
	dropCountList.AddItem(25, 1)
	dropCountList.AddItem(26, 1)

	megaphoneDropCountList.AddItem(0, 810)
	megaphoneDropCountList.AddItem(1, 100)
	megaphoneDropCountList.AddItem(2, 75)
	megaphoneDropCountList.AddItem(3, 15)
}

func ExecuteLesson(session *userdata.Session, req request.ExecuteLessonRequest) response.ExecuteLessonResponse {
	resp := response.ExecuteLessonResponse{
		UserModelDiff: &session.UserModel,
	}

	result := response.LessonResultResponse{
		SelectedDeckId: req.SelectedDeckId,
	}

	deck := user_lesson_deck.GetUserLessonDeck(session, req.SelectedDeckId)
	repeatCount := int32(1)
	if req.IsThreeTimes {
		repeatCount = 3
	}
	if config.Conf.ResourceConfig().ConsumeAp {
		user_status.AddUserAp(session, -repeatCount)
	}
	// update mission progress
	user_mission.UpdateProgress(session, enum.MissionClearConditionTypeCountLesson, nil, nil,
		func(session *userdata.Session, missionList []any, _ ...any) {
			for _, mission := range missionList {
				user_mission.AddMissionProgress(session, mission, repeatCount)
			}
		})

	session.UserStatus.LessonResumeStatus = enum.TopPriorityProcessStatusLesson

	enhancingItems := map[int32]*client.Content{}

	for _, itemId := range req.ConsumedContentIds.Slice {
		item := user_content.GetUserContent(session, enum.ContentTypeLessonEnhancingItem, itemId)
		enhancingItems[itemId] = &item
	}

	resp.IsSubscription = user_subscription_status.HasSubscription(session)

	for lesson := int32(1); lesson <= 4; lesson++ {
		actions := generic.List[client.LessonMenuAction]{}
		for i := 1; i <= 9; i++ {
			cardMasterId := reflect.ValueOf(deck).Field(i + 1).Interface().(generic.Nullable[int32]).Value
			actions.Append(client.LessonMenuAction{
				CardMasterId: cardMasterId,
				Position:     int32(i),
			})
		}
		resp.LessonMenuActions.Set(lesson%4, actions)
		resp.LessonDropRarityList.Set(lesson%4, generic.List[int32]{})
	}

	isMemberGuildRankingPeriod := user_member_guild.IsMemberGuildRankingPeriod(session)

	for repeat := int32(1); repeat <= repeatCount; repeat++ {
		usedItems := []int32{}
		for _, itemId := range req.ConsumedContentIds.Slice {
			if enhancingItems[itemId].ContentAmount > 0 {
				enhancingItems[itemId].ContentAmount--
				usedItems = append(usedItems, itemId)
			}
		}

		// handle skill here if we want
		gainedItems := []client.LessonDropItem{}

		// use default drop, but switch to other drop if necessary

		for lesson := int32(1); lesson <= 3; lesson++ {
			lessonMenu := session.Gamedata.LessonMenu[req.ExecuteLessonIds.Slice[lesson-1]]
			dropList := lessonMenu.DefaultDrop
			for _, item := range usedItems {
				drop, exist := lessonMenu.Drop[item]
				if exist {
					dropList = drop
				}
			}

			dropCount := dropCountList.GetRandomItem()
			gainedRarity := []int32{}

			dropRarityList := resp.LessonDropRarityList.GetOnly(lesson)
			for i := int32(0); i < dropCount; i++ {
				drop := dropList.GetRandomItem()
				if drop.DropRarity > enum.LessonDropRarityTypeRare1 {
					gainedRarity = append(gainedRarity, enum.LessonDropRarityTypeRare2)
				} else {
					gainedRarity = append(gainedRarity, enum.LessonDropRarityTypeRare1)
				}
				gainedItems = append(gainedItems, drop)
			}

			// megaphone, only drop when ranking is on
			if isMemberGuildRankingPeriod {
				megaphoneDrop := megaphoneDropCountList.GetRandomItem()
				for i := int32(0); i < megaphoneDrop; i++ {
					gainedItems = append(gainedItems, client.LessonDropItem{
						ContentType:   item.RallyMegaphone.ContentType,
						ContentId:     item.RallyMegaphone.ContentId,
						ContentAmount: item.RallyMegaphone.ContentAmount,
						DropRarity:    4, // this field is not enum
					})
					gainedRarity = append(gainedRarity, enum.LessonDropRarityTypeRare2)
				}
			}

			for _, content := range gainedItems {
				user_content.AddContent(session, client.Content{
					ContentType:   content.ContentType,
					ContentId:     content.ContentId,
					ContentAmount: content.ContentAmount,
				})
			}
			for _, rarity := range gainedRarity {
				dropRarityList.Append(rarity)
			}

			if resp.IsSubscription {
				for _, rarity := range gainedRarity {
					dropRarityList.Append(rarity)
				}
				for _, content := range gainedItems {
					user_content.AddContent(session, client.Content{
						ContentType:   content.ContentType,
						ContentId:     content.ContentId,
						ContentAmount: content.ContentAmount,
					})
				}
			}
		}

		for _, drop := range gainedItems {
			result.DropItemList.Append(drop)
		}

		if resp.IsSubscription {
			for _, drop := range gainedItems {
				drop.IsSubscription = true
				result.DropItemList.Append(drop)
			}
		}

		if (repeat == 1) && (repeat < repeatCount) {
			sort.Slice(req.ExecuteLessonIds.Slice, func(i, j int) bool {
				return req.ExecuteLessonIds.Slice[i] < req.ExecuteLessonIds.Slice[j]
			})
		}
	}

	for _, item := range enhancingItems {
		user_content.UpdateUserContent(session, *item)
	}

	// insight skills

	// randomize funcion & gacha like as temporary
	if *config.Conf.LessonDropSkillType != "fixed" {
		rarity5 := []int32{30000045, 30000071, 30000072, 30000074, 30000079, 30000522, 30000527} // Ultra Rare
		rarity4 := []int32{30000005, 30000060, 30000061, 30000062, 30000064, 30000069, 30000075, 30000076, 30000078, 30000081, 30000082, 30000084, 30000089, 30000101, 30000102, 30000104, 30000109, 30000101, 30000102, 30000104, 30000109, 30000111, 30000112, 30000114, 30000119, 30000121, 30000122, 30000124, 30000129, 30000131, 30000132, 30000134, 30000139, 30000166, 30000167, 30000169, 30000174, 30000243, 30000250, 30000251, 30000253, 30000254, 30000317, 30000318, 30000320, 30000325, 30000412, 30000413, 30000415, 30000420, 30000523, 30000528, 30000529} // SSR
		rarity3 := []int32{30000046, 30000047, 30000048, 30000049, 30000050, 30000051, 30000053, 30000058, 30000065, 30000066, 30000068, 30000085, 30000086, 30000088, 30000105, 30000106, 30000108, 30000105, 30000106, 30000108, 30000115, 30000116, 30000118, 30000125, 30000126, 30000128, 30000135, 30000136, 30000138, 30000155, 30000156, 30000157, 30000159, 30000164, 30000170, 30000171, 30000173, 30000176, 30000177, 30000179, 30000184, 30000196, 30000197, 30000199, 30000204, 30000196, 30000197, 30000199, 30000204, 30000206, 30000207, 30000209, 30000214, 30000216, 30000217, 30000219, 30000224, 30000226, 30000227, 30000229, 30000234, 30000244, 30000245, 30000247, 30000248, 30000256, 30000257, 30000259, 30000260, 30000268, 30000269, 30000271, 30000272, 30000268, 30000269, 30000271, 30000272, 30000274, 30000275, 30000277, 30000278, 30000280, 30000281, 30000283, 30000284, 30000286, 30000287, 30000289, 30000290, 30000306, 30000307, 30000308, 30000310, 30000315, 30000321, 30000322, 30000324, 30000327, 30000328, 30000330, 30000335, 30000347, 30000348, 30000350, 30000355, 30000347, 30000348, 30000350, 30000355, 30000357, 30000358, 30000360, 30000365, 30000367, 30000368, 30000370, 30000375, 30000377, 30000378, 30000380, 30000385, 30000401, 30000402, 30000403, 30000405, 30000410, 30000416, 30000417, 30000419, 30000422, 30000423, 30000425, 30000430, 30000442, 30000443, 30000445, 30000450, 30000442, 30000443, 30000445, 30000450, 30000452, 30000453, 30000455, 30000460, 30000462, 30000463, 30000465, 30000470, 30000472, 30000473, 30000475, 30000480, 30000524, 30000530, 30000531} // Super Rare
		rarity2 := []int32{30000011, 30000012, 30000014, 30000021, 30000022, 30000024, 30000021, 30000022, 30000024, 30000026, 30000027, 30000029, 30000031, 30000032, 30000034, 30000036, 30000037, 30000039, 30000041, 30000042, 30000044, 30000054, 30000055, 30000057, 30000059, 30000141, 30000142, 30000143, 30000144, 30000145, 30000146, 30000148, 30000153, 30000160, 30000161, 30000163, 30000180, 30000181, 30000183, 30000200, 30000201, 30000203, 30000200, 30000201, 30000203, 30000210, 30000211, 30000213, 30000220, 30000221, 30000223, 30000230, 30000231, 30000233, 30000236, 30000237, 30000238, 30000240, 30000241, 30000242, 30000292, 30000293, 30000294, 30000295, 30000296, 30000297, 30000299, 30000304, 30000311, 30000312, 30000314, 30000331, 30000332, 30000334, 30000351, 30000352, 30000354, 30000351, 30000352, 30000354, 30000361, 30000362, 30000364, 30000371, 30000372, 30000374, 30000381, 30000382, 30000384, 30000387, 30000388, 30000389, 30000390, 30000391, 30000392, 30000394, 30000399, 30000406, 30000407, 30000409, 30000426, 30000427, 30000429, 30000446, 30000447, 30000449, 30000446, 30000447, 30000449, 30000456, 30000457, 30000459, 30000466, 30000467, 30000469, 30000476, 30000477, 30000479, 30000482, 30000483, 30000485, 30000487, 30000488, 30000490, 30000492, 30000493, 30000495, 30000502, 30000503, 30000505, 30000502, 30000503, 30000505, 30000507, 30000508, 30000510, 30000512, 30000513, 30000515, 30000517, 30000518, 30000520, 30000525, 30000532, 30000533} // Rare
		rarity1 := []int32{30000001, 30000002, 30000004, 30000006, 30000007, 30000009, 30000149, 30000150, 30000152, 30000154, 30000300, 30000301, 30000303, 30000305, 30000395, 30000396, 30000398, 30000400, 30000526} // Common
		rand.Seed(time.Now().UnixNano())
		rarityProbabilities := []float64{0.005, 0.015, 0.03, 0.20, 0.75} // Example probabilities: 1%, 4%, 15%, 30%, 50%
		skillCountProbabilities := []float64{0.70, 0.20, 0.07, 0.02, 0.01} // Example probabilities: 50%, 30%, 15%, 4%, 1%
		getRandomSkill := func() int32 {
			ambasing := rand.Float64()
			switch {
			case ambasing < rarityProbabilities[0]:
				return rarity5[rand.Intn(len(rarity5))]
			case ambasing < rarityProbabilities[0]+rarityProbabilities[1]:
				return rarity4[rand.Intn(len(rarity4))]
			case ambasing < rarityProbabilities[0]+rarityProbabilities[1]+rarityProbabilities[2]:
				return rarity3[rand.Intn(len(rarity3))]
			case ambasing < rarityProbabilities[0]+rarityProbabilities[1]+rarityProbabilities[2]+rarityProbabilities[3]:
				return rarity2[rand.Intn(len(rarity2))]
			default:
				return rarity1[rand.Intn(len(rarity1))]
			}
		}
		getSkillCount := func() int {
			nissan := rand.Float64()
			switch {
			case nissan < skillCountProbabilities[0]:
				return 0
			case nissan < skillCountProbabilities[0]+skillCountProbabilities[1]:
				return 1
			case nissan < skillCountProbabilities[0]+skillCountProbabilities[1]+skillCountProbabilities[2]:
				return 2
			case nissan < skillCountProbabilities[0]+skillCountProbabilities[1]+skillCountProbabilities[2]+skillCountProbabilities[3]:
				return 3
			default:
				return 4
			}
		}
		for position := int32(1); position <= 9; position++ {
			skillCount := getSkillCount()
			for buss := 0; buss < skillCount; buss++ {
				skillId := getRandomSkill()
				result.DropSkillList.Append(client.LessonResultDropPassiveSkill{
					Position:       position,
					PassiveSkillId: skillId,
				})
			}
		}
	} else {
		data, err := ioutil.ReadFile("insightskills.json")
		if err != nil {
			log.Fatalf("Error reading file: %v", err)
		}

		// Unmarshal the JSON data into the SkillData struct
		var skillData SkillData
		err = json.Unmarshal(data, &skillData)
		if err != nil {
			log.Fatalf("Error unmarshalling JSON: %v", err)
		}

		// Use the position and skills from the JSON file
		for positionStr, skills := range skillData.Positions {
			position, err := strconv.ParseInt(positionStr, 10, 32)
			if err != nil {
				log.Fatalf("Error converting position string to int32: %v", err)
			}

			positionInt32 := int32(position) // Convert to int32
			for _, skillId := range skills {
				result.DropSkillList.Append(client.LessonResultDropPassiveSkill{
					Position:       positionInt32,
					PassiveSkillId: skillId,
				})
			}
		}
	}
	userdata.GenericDatabaseInsert(session, "u_lesson", result)

	return resp
}