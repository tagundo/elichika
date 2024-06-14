# Endpoints
Here is a list of endpoints found in the client, for reference.

Ticked endpoint means that the server see the end point (not 404), it doesn't mean the feature is correctly or fully handled.

Also note that some endpoints won't need to be handled at all either because they're no longer used, or because they are just irrelevant, or because they are not even endpoint and just look like one.

## Done
- [x] /accessory/allUnequip
- [x] /accessory/melt
- [x] /accessory/powerUp
- [x] /accessory/rarityUp
- [x] /accessory/updateIsLock
- [x] /accessory/updateIsNew
- [x] /asset/getPackUrl
- [x] /billing/fetchBillingHistory
- [x] /billing/updateSubscription
- [x] /bootstrap/fetchBootstrap
- [x] /bootstrap/getClearedPlatformAchievement
- [x] /card/changeFavorite
- [x] /card/changeIsAwakeningImage
- [x] /card/getOtherUserCard
- [x] /card/updateCardNewFlag
- [x] /communicationMember/fetchCommunicationMemberDetail
- [x] /communicationMember/finishUserStoryMember
- [x] /communicationMember/finishUserStorySide
- [x] /communicationMember/setFavoriteMember
- [x] /communicationMember/setTheme
- [x] /communicationMember/updateUserCommunicationMemberDetailBadge       
- [x] /communicationMember/updateUserLiveDifficultyNewFlag
- [x] /dailyTheater/fetchDailyTheater
- [x] /dailyTheater/setLike
- [x] /dailyTheaterArchive/fetchDailyTheaterArchive
- [x] /dataLink/fetchDataLinks
- [x] /dataLink/fetchGameServiceDataBeforeLogin
- [x] /emblem/activateEmblem
- [x] /emblem/fetchEmblem
- [x] /emblem/fetchEmblemById
- [x] /friend/apply
- [x] /friend/applyOtherScene
- [x] /friend/approve
- [x] /friend/approveOtherScene
- [x] /friend/cancel
- [x] /friend/cancelOtherScene
- [x] /friend/fetchFriendList
- [x] /friend/refuse
- [x] /friend/remove
- [x] /friend/removeOtherScene
- [x] /friend/searchUserId
- [x] /gacha/draw
- [x] /gacha/fetchGachaMenu
- [x] /gameSettings/updatePushNotificationSettings
- [x] /gdpr/updateConsentState
- [x] /infoTrigger/read
- [x] /infoTrigger/readByType
- [x] /infoTrigger/readCardGradeUp
- [x] /infoTrigger/readMemberGuildRankingResult
- [x] /infoTrigger/readMemberGuildSupportItemExpired
- [x] /infoTrigger/readMemberLoveLevelUp
- [x] /itemDetail/fetchItemDetailRelateLiveList
- [x] /lesson/changeDeckNameLessonDeck
- [x] /lesson/executeLesson
- [x] /lesson/resultLesson
- [x] /lesson/saveDeck
- [x] /lesson/skillEditResult
- [x] /live/fetchLiveMusicSelect
- [x] /live/finish
- [x] /live/finishTutorial
- [x] /live/resume
- [x] /live/skip
- [x] /live/start
- [x] /live/surrender
- [x] /live/updatePlayList
- [x] /liveDeck/changeDeckNameLiveDeck
- [x] /liveDeck/fetchLiveDeckSelect
- [x] /liveDeck/saveDeck
- [x] /liveDeck/saveDeckAll
- [x] /liveDeck/saveSuit
- [x] /liveMv/saveDeck
- [x] /liveMv/start
- [x] /livePartners/fetch
- [x] /livePartners/setLivePartner
- [x] /login/login
- [x] /login/startup
- [x] /loginBonus/readLoginBonus
- [x] /loveRanking/fetch
- [x] /member/openMemberLovePanel
- [x] /memberGuild/cheerMemberGuild
- [x] /memberGuild/fetchMemberGuildRanking
- [x] /memberGuild/fetchMemberGuildRankingYear
- [x] /memberGuild/fetchMemberGuildSelect
- [x] /memberGuild/fetchMemberGuildTop
- [x] /memberGuild/joinMemberGuild
- [x] /mission/clearMissionNewBadge
- [x] /mission/fetchMission
- [x] /mission/receiveReward
- [x] /navi/saveUserNaviVoice
- [x] /navi/tapLovePoint
- [x] /notice/fetchNotice
- [x] /notice/fetchNoticeDetail
- [x] /present/fetch
- [x] /present/receive
- [x] /referenceBook/saveReferenceBook
- [x] /ruleDescription/saveRuleDescription
- [x] /sceneTips/saveSceneTipsType
- [x] /shop/fetchShopPack
- [x] /shop/fetchShopSnsCoin
- [x] /shop/fetchShopSubscription
- [x] /shop/fetchShopTop
- [x] /sif2DataLink/dataLink
- [x] /still/fetch
- [x] /subscription/fetchSubscriptionPass
- [x] /takeOver/checkTakeOver
- [x] /takeOver/setTakeOver
- [x] /takeOver/updatePassWord
- [x] /terms/agreement
- [x] /tower/clearedTowerFloor
- [x] /tower/fetchTowerSelect
- [x] /tower/fetchTowerTop
- [x] /tower/recoveryTowerCardUsed
- [x] /tower/recoveryTowerCardUsedAll
- [x] /towerRanking/fetchTowerRanking
- [x] /trade/executeMultiTrade
- [x] /trade/executeTrade
- [x] /trade/fetchTrade
- [x] /trainingTree/activateTrainingTreeCell
- [x] /trainingTree/fetchTrainingTree
- [x] /trainingTree/gradeUpCard
- [x] /trainingTree/levelUpCard
- [x] /tutorial/corePlayableEnd
- [x] /tutorial/phaseEnd
- [x] /tutorial/timingAdjusterEnd
- [x] /tutorial/tutorialSkip
- [x] /unlockScene/saveUnlockedScene
- [x] /user/addAccessoryBoxLimit
- [x] /user/recoverLp
- [x] /user/recoverLpSubscription
- [x] /userAccountDeletion/checkUserAccountDeleted
- [x] /userProfile/fetchProfile
- [x] /userProfile/setCommboLive
- [x] /userProfile/setProfile
- [x] /userProfile/setProfileBirthday
- [x] /userProfile/setRecommendCard
- [x] /userProfile/setScoreLive
- [x] /voltageRanking/getVoltageRanking
- [x] /voltageRanking/getVoltageRankingDeck

## Not Planned
### Not Necessary
- [ ] (not necessary) /billing/applePurchase 
- [ ] (not necessary) /billing/googlePurchase
- [ ] (not necessary) /billing/prePurchase
- [ ] (not necessary) /billing/purchaseSubscriptionTrial
- [ ] (not necessary) /billing/restoreAppleSubscription
- [ ] (not necessary) /billing/restoreGoogleSubscription
- [ ] (not necessary) /billing/saveOperationLog
- [ ] (not necessary) /billing/saveUserBirth
- [ ] (not necessary) /caution/read
- [ ] (not necessary) /communicationMember/updateUserCardNewFlag
- [ ] (not necessary) /communicationMember/updateUserCustomBackgroundNewFlag
- [ ] (not necessary) /communicationMember/updateUserStoryMemberNewFlag
- [ ] (not necessary) /communicationMember/updateUserStorySideNewFlag
- [ ] (not necessary) /communicationMember/updateUserSuitNewFlag
- [ ] (not necessary) /communicationMember/updateUserThemeNewFlag
- [ ] (not necessary) /communicationMember/updateUserVoiceNewFlag
- [ ] (not necessary) /dataLink/fetchGameServiceData
- [ ] (not necessary) /dataLink/fetchSchoolIdolFestivalIdDataAfterLogin
- [ ] (not necessary) /dataLink/fetchSchoolIdolFestivalIdDataBeforeLogin
- [ ] (not necessary) /dataLink/linkGameService
- [ ] (not necessary) /dataLink/linkOnStartUpGameService
- [ ] (not necessary) /dataLink/linkSchoolIdolFestivalId
- [ ] (not necessary) /dataLink/migrateGameService
- [ ] (not necessary) /dataLink/migrateGameServiceBeforeLogin
- [ ] (not necessary) /dataLink/migrateSchoolIdolFestivalId
- [ ] (not necessary) /dataLink/migrateSchoolIdolFestivalIdBeforeLogin
- [ ] (not necessary) /dataLink/unlinkGameService
- [ ] (not necessary) /dataLink/unlinkSchoolIdolFestivalId
- [ ] (not necessary) /lesson/resetDeck
- [ ] (not necessary) /liveDeck/changeNameLiveParty
- [ ] (not necessary) /liveDeck/resetDeck
- [ ] (not necessary) /liveDeck/saveOverwriteDeck
- [ ] (not necessary) /liveDeck/saveSquad
- [ ] (not necessary) /member/fetchMemberLovePanel
- [ ] (not necessary) /refundInformation/fetchRefundInformation
- [ ] (not necessary) /reviewRequest/finishReviewRequestProcessFlow
- [ ] (not necessary) /shop/exchangeShopItemExchange
- [ ] (not necessary) /shop/fetchShopItemExchange
- [ ] (not necessary) /subscription/readContinueReward
- [ ] (not necessary) /tutorial/playableTutorialSkip
- [ ] (not necessary?) /shop/exchangeShopEventExchange
- [ ] (not necessary?) /shop/fetchShopEventExchange
- [ ] (not necessary?) /userProfile/fetchDeck
- [ ] (the button for this is not in the app?, we need to turn it back on first) /userAccountDeletion/deleteUserAccount
### Challenge
- [ ] /challenge/fetchBeginner
- [ ] /challenge/receiveRewardBeginner
### SBL
- [ ] /coop/login
- [ ] /coopLive/create
- [ ] /coopLive/createRoom
- [ ] /coopLive/fetchRoomFinish
- [ ] /coopLive/fetchRoomHistory
- [ ] /coopLive/fetchRoomHistoryDeck
- [ ] /coopLive/fetchRoomResultUserDeck
- [ ] /coopLive/finishRoom
- [ ] /coopLive/finishSolo
- [ ] /coopLive/start
- [ ] /eventCoop/fetchLobby
- [ ] /eventCoopRanking/fetchEventCoopRanking
### Story Event
- [ ] /eventMarathon/fetchEventMarathon
- [ ] /eventMarathon/finishEventStory
- [ ] /eventMarathonRanking/fetchEventMarathonRanking
### Exchange Event
- [ ] /eventMining/fetchEventMining
- [ ] /eventMining/finishEventMiningStory
- [ ] /eventMining/likeEventMiningPanel
- [ ] /eventMiningRanking/fetchEventMiningRanking
### External Movie (story)
- [ ] /externalMovie/fetchBrowseExternalMovie
- [ ] /externalMovie/saveBrowseExternalMovie
### Gacha
- [ ] /gacha/fixRetry
- [ ] /gacha/retry
### GPS
- [ ] /gpsPresent/saveCampaignLocation
### Info Trigger
- [ ] /infoTrigger/readEventCommonShowResult
- [ ] /infoTrigger/readEventMarathonResult
- [ ] /infoTrigger/readEventMiningResult
- [ ] /infoTrigger/readExpiredGiftBox
- [ ] /infoTrigger/readGachaPointExchange
- [ ] /infoTrigger/readSubscriptionEnd
- [ ] /infoTrigger/readSubscriptionTrialEnd
### Live
- [ ] /live/recoverDailyLiveMusicPlayable
### None
- [ ] /noop/noop
### Notice
- [ ] /notice/fetchNoticeList
- [ ] /notice/saveUserSuperNotice
### SBL?
- [ ] /room/
- [ ] /rooms
- [ ] /rooms/filter
- [ ] /rooms/filter/assign
- [ ] /rooms/number/
### SIF ID Reward
- [ ] /schoolIdolFestivalIdReward/fetch
### Steady Ranking
- [ ] /steadyRanking/fetch
- [ ] /steadyRanking/getSteadyRankingDeck
- [ ] /steadyRanking/selectDifficulty
### User
- [ ] /user/recoverAp
