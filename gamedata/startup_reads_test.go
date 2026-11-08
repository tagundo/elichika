package gamedata

import (
	"elichika/client"
	"elichika/db"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"xorm.io/xorm"
)

func startupFixture(t *testing.T, statements []string) *db.DatabaseSync {
	t.Helper()
	database, err := db.NewDatabase(filepath.Join(t.TempDir(), "startup.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { database.Close() })
	database.Do(func(session *xorm.Session) {
		for _, sql := range statements {
			if _, err = session.Exec(sql); err != nil {
				return
			}
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	return database
}

func oldLiveDetails(t *testing.T, database *db.DatabaseSync, ids []int32) map[int32]*LiveDifficulty {
	t.Helper()
	result := make(map[int32]*LiveDifficulty)
	var err error
	database.Do(func(session *xorm.Session) {
		for _, id := range ids {
			ld := &LiveDifficulty{LiveDifficultyId: id}
			result[id] = ld
			if err = session.Table("m_live_difficulty_mission").Where("live_difficulty_master_id = ?", id).OrderBy("position").Find(&ld.Missions); err != nil {
				return
			}
			if err = session.Table("m_live_difficulty_gimmick").Where("live_difficulty_master_id = ?", id).Find(&ld.LiveDifficultyGimmicks); err != nil {
				return
			}
			if err = session.Table("m_live_difficulty_note_gimmick").Where("live_difficulty_id = ?", id).Find(&ld.LiveDifficultyNoteGimmicks); err != nil {
				return
			}
			for i := range ld.LiveDifficultyNoteGimmicks {
				ld.LiveDifficultyNoteGimmicks[i].populate()
			}
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func compareLiveDetails(t *testing.T, database *db.DatabaseSync, ids []int32) {
	t.Helper()
	start := time.Now()
	want := oldLiveDetails(t, database, ids)
	oldTime := time.Since(start)
	got := &Gamedata{MasterdataDb: database, LiveDifficulty: make(map[int32]*LiveDifficulty)}
	for _, id := range ids {
		got.LiveDifficulty[id] = &LiveDifficulty{LiveDifficultyId: id}
	}
	start = time.Now()
	loadLiveDifficultyDetails(got)
	newTime := time.Since(start)
	if !reflect.DeepEqual(want, got.LiveDifficulty) {
		t.Fatal("grouped live details differ from the previous per-owner queries")
	}
	t.Logf("%d live difficulties: old queries %s; grouped %s", len(ids), oldTime, newTime)
}

func TestStartupLiveDetailsPreserveOrderingAndCustomIndexFallback(t *testing.T) {
	database := startupFixture(t, []string{
		`CREATE TABLE m_live_difficulty (live_difficulty_id INTEGER PRIMARY KEY)`,
		`INSERT INTO m_live_difficulty VALUES(1),(2),(3)`,
		`CREATE TABLE m_live_difficulty_mission (live_difficulty_master_id INTEGER, position INTEGER, target_type INTEGER, content_type INTEGER, content_id INTEGER, content_amount INTEGER, PRIMARY KEY(live_difficulty_master_id,position))`,
		`CREATE TABLE m_live_difficulty_gimmick (id INTEGER PRIMARY KEY,live_difficulty_master_id INTEGER,trigger_type INTEGER,condition_master_id1 INTEGER,condition_master_id2 INTEGER,skill_master_id INTEGER)`,
		`CREATE TABLE m_live_difficulty_note_gimmick (live_difficulty_id INTEGER,note_id INTEGER,note_gimmick_type INTEGER,note_gimmick_icon_type INTEGER,skill_master_id INTEGER,name TEXT,PRIMARY KEY(live_difficulty_id,note_id))`,
		`INSERT INTO m_live_difficulty_mission VALUES(1,2,3,4,5,6),(1,1,7,8,9,10),(999,1,1,1,1,1)`,
		`INSERT INTO m_live_difficulty_gimmick VALUES(7,1,1,2,NULL,3),(3,1,4,5,6,7),(8,2,8,9,NULL,10),(9,999,1,1,1,'unused orphan invalid number')`,
		`INSERT INTO m_live_difficulty_note_gimmick VALUES(1,8,1,2,3,'note00000007'),(1,2,4,5,6,'note00000009'),(999,1,1,1,1,'note00000001')`,
	})
	compareLiveDetails(t, database, []int32{1, 2, 3})
	var err error
	database.Do(func(session *xorm.Session) {
		_, err = session.Exec(`CREATE INDEX mod_gimmick_order ON m_live_difficulty_gimmick(live_difficulty_master_id,skill_master_id DESC)`)
	})
	if err != nil {
		t.Fatal(err)
	}
	compareLiveDetails(t, database, []int32{1, 2, 3})
}

func oldTreeDetails(t *testing.T, database *db.DatabaseSync, trees map[int32]*TrainingTree) {
	t.Helper()
	g := &Gamedata{MasterdataDb: database, TrainingTree: trees, TrainingTreeMapping: map[int32]*TrainingTreeMapping{1: {Id: 1}}}
	for _, tree := range trees {
		id := int32(1)
		tree.TrainingTreeMappingMId = &id
		tree.populate(g, false)
	}
	// These links are populated after detail loading in both paths.
	for _, tree := range trees {
		tree.TrainingTreeMappingMId = nil
		tree.TrainingTreeMapping = nil
	}
}

func compareTreeDetails(t *testing.T, database *db.DatabaseSync, ids map[int32]int32) {
	t.Helper()
	want, got := make(map[int32]*TrainingTree), make(map[int32]*TrainingTree)
	for id, param := range ids {
		want[id] = &TrainingTree{Id: id, TrainingTreeCardParamMId: param}
		got[id] = &TrainingTree{Id: id, TrainingTreeCardParamMId: param}
	}
	start := time.Now()
	oldTreeDetails(t, database, want)
	oldTime := time.Since(start)
	start = time.Now()
	loaded, err := loadTrainingTreeDetails(&Gamedata{MasterdataDb: database, TrainingTree: got})
	newTime := time.Since(start)
	if err != nil || !loaded {
		t.Fatalf("expected standard grouped tree schema: loaded=%v err=%v", loaded, err)
	}
	if !reflect.DeepEqual(want, got) {
		t.Fatal("grouped tree details differ from previous per-owner queries")
	}
	t.Logf("%d training trees: old queries %s; grouped %s", len(ids), oldTime, newTime)
}

func TestStartupTrainingTreePreservesSentinelsOverwritesAndIndependentSlices(t *testing.T) {
	database := startupFixture(t, []string{
		`CREATE TABLE m_training_tree (id INTEGER PRIMARY KEY,training_tree_card_param_m_id INTEGER)`,
		`INSERT INTO m_training_tree VALUES(1,10),(2,10),(3,30)`,
		`CREATE TABLE m_training_tree_card_param (id INTEGER,training_content_no INTEGER,training_content_type INTEGER,value INTEGER,PRIMARY KEY(id,training_content_no))`,
		`CREATE TABLE m_training_tree_card_story_side (card_m_id INTEGER,training_content_type INTEGER,training_content_no INTEGER,story_side_m_id INTEGER,PRIMARY KEY(card_m_id,training_content_type,training_content_no))`,
		`CREATE TABLE m_training_tree_card_suit (card_m_id INTEGER,training_content_no INTEGER,suit_m_id INTEGER UNIQUE,PRIMARY KEY(card_m_id,training_content_no))`,
		`CREATE TABLE m_training_tree_card_voice (card_m_id INTEGER,training_content_no INTEGER,navi_action_id INTEGER,PRIMARY KEY(card_m_id,training_content_no))`,
		`CREATE TABLE m_training_tree_progress_reward (card_master_id INTEGER,activate_num INTEGER,display_order INTEGER,content_type INTEGER,content_id INTEGER,content_amount INTEGER,PRIMARY KEY(card_master_id,activate_num,display_order))`,
		`INSERT INTO m_training_tree_card_param VALUES(10,2,1,200),(10,1,1,100),(999,1,1,3)`,
		`INSERT INTO m_training_tree_card_story_side VALUES(1,3,2,302),(1,3,1,301),(999,1,1,1)`,
		`INSERT INTO m_training_tree_card_suit VALUES(1,2,102),(1,1,101)`,
		`INSERT INTO m_training_tree_card_voice VALUES(1,2,202),(1,1,201)`,
		`INSERT INTO m_training_tree_progress_reward VALUES(1,5,2,1,2,3),(1,5,1,4,5,6),(999,1,1,1,1,1)`,
	})
	compareTreeDetails(t, database, map[int32]int32{1: 10, 2: 10, 3: 30})
	g := &Gamedata{MasterdataDb: database, TrainingTree: map[int32]*TrainingTree{1: {Id: 1, TrainingTreeCardParamMId: 10}, 2: {Id: 2, TrainingTreeCardParamMId: 10}}}
	loaded, err := loadTrainingTreeDetails(g)
	if err != nil || !loaded {
		t.Fatal(loaded, err)
	}
	g.TrainingTree[1].TrainingTreeCardParams[1].Value = -1
	if g.TrainingTree[2].TrainingTreeCardParams[1].Value != 100 {
		t.Fatal("trees sharing a parameter group also share mutable slices")
	}
	var setupErr error
	database.Do(func(session *xorm.Session) {
		_, setupErr = session.Exec(`CREATE INDEX mod_tree_order ON m_training_tree_card_story_side(card_m_id,story_side_m_id DESC)`)
	})
	if setupErr != nil {
		t.Fatal(setupErr)
	}
	untouched := &Gamedata{MasterdataDb: database, TrainingTree: map[int32]*TrainingTree{1: {Id: 1}}}
	loaded, err = loadTrainingTreeDetails(untouched)
	if err != nil || loaded || untouched.TrainingTree[1].TrainingTreeCardParams != nil {
		t.Fatal("nonstandard schema must fall back before mutating trees")
	}
}

func TestStartupMappingAndRewardReadsPreserveEmptyAndFirstRow(t *testing.T) {
	database := startupFixture(t, []string{
		`CREATE TABLE m_training_tree_mapping(id INTEGER PRIMARY KEY,training_tree_cell_content_m_id INTEGER)`,
		`INSERT INTO m_training_tree_mapping VALUES(1,10),(2,10),(3,30)`,
		`CREATE TABLE m_story_member(id INTEGER PRIMARY KEY)`,
		`INSERT INTO m_story_member VALUES(1),(2)`,
		`CREATE TABLE m_training_tree_cell_content (id INTEGER,cell_id INTEGER,training_tree_cell_type INTEGER,training_content_no INTEGER,required_grade INTEGER,training_tree_cell_item_set_m_id INTEGER,sns_coin INTEGER,PRIMARY KEY(id,cell_id),UNIQUE(id,training_tree_cell_type,training_content_no))`,
		`INSERT INTO m_training_tree_cell_content VALUES(10,2,1,2,3,4,5),(10,1,2,1,6,7,8),(999,1,1,1,1,1,1)`,
		`CREATE TABLE m_story_member_rewards (story_member_master_id INTEGER,display_order INTEGER,content_type INTEGER,content_id INTEGER,content_amount INTEGER,PRIMARY KEY(story_member_master_id,content_type,content_id))`,
		`INSERT INTO m_story_member_rewards VALUES(1,1,3,90,1),(1,9,2,80,5),(999,1,1,1,1)`,
	})
	mappings := map[int32]*TrainingTreeMapping{1: {Id: 1, TrainingTreeCellContentMId: 10}, 2: {Id: 2, TrainingTreeCellContentMId: 10}, 3: {Id: 3, TrainingTreeCellContentMId: 30}}
	g := &Gamedata{MasterdataDb: database, TrainingTreeMapping: mappings, StoryMember: map[int32]*StoryMember{1: {Id: 1}, 2: {Id: 2}}}
	loaded, err := loadTrainingMappingDetails(g)
	if err != nil || !loaded {
		t.Fatal(loaded, err)
	}
	for _, mapping := range mappings {
		var want []TrainingTreeCellContent
		database.Do(func(session *xorm.Session) {
			err = session.Table("m_training_tree_cell_content").Where("id = ?", mapping.TrainingTreeCellContentMId).OrderBy("cell_id").Find(&want)
		})
		if err != nil || !reflect.DeepEqual(want, mapping.TrainingTreeCellContents) {
			t.Fatal("mapping cells/order changed", err)
		}
	}
	mappings[1].TrainingTreeCellContents[0].CellId = -1
	if mappings[2].TrainingTreeCellContents[0].CellId != 1 {
		t.Fatal("mapping cell slices alias")
	}
	loaded, err = loadStoryMemberRewards(g)
	if err != nil || !loaded {
		t.Fatal(loaded, err)
	}
	for id, story := range g.StoryMember {
		var want client.Content
		var found bool
		database.Do(func(session *xorm.Session) {
			found, err = session.Table("m_story_member_rewards").Where("story_member_master_id = ?", id).Get(&want)
		})
		if err != nil || found != (story.Reward != nil) || (found && !reflect.DeepEqual(want, *story.Reward)) {
			t.Fatal("first reward or missing reward behavior changed", err)
		}
	}
}

func compareMappingAndStoryDetails(t *testing.T, database *db.DatabaseSync) {
	t.Helper()
	want := &Gamedata{MasterdataDb: database, TrainingTreeMapping: make(map[int32]*TrainingTreeMapping), StoryMember: make(map[int32]*StoryMember)}
	got := &Gamedata{MasterdataDb: database, TrainingTreeMapping: make(map[int32]*TrainingTreeMapping), StoryMember: make(map[int32]*StoryMember)}
	var err error
	database.Do(func(session *xorm.Session) {
		err = session.Table("m_training_tree_mapping").Find(&want.TrainingTreeMapping)
		if err == nil {
			err = session.Table("m_story_member").Find(&want.StoryMember)
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	for id, mapping := range want.TrainingTreeMapping {
		copy := *mapping
		got.TrainingTreeMapping[id] = &copy
	}
	for id, story := range want.StoryMember {
		copy := *story
		got.StoryMember[id] = &copy
	}
	start := time.Now()
	database.Do(func(session *xorm.Session) {
		for _, mapping := range want.TrainingTreeMapping {
			if err = session.Table("m_training_tree_cell_content").Where("id = ?", mapping.TrainingTreeCellContentMId).OrderBy("cell_id").Find(&mapping.TrainingTreeCellContents); err != nil {
				return
			}
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, story := range want.StoryMember {
		story.populate(want)
	}
	oldTime := time.Since(start)
	start = time.Now()
	loaded, err := loadTrainingMappingDetails(got)
	if err != nil || !loaded {
		t.Fatal(loaded, err)
	}
	loaded, err = loadStoryMemberRewards(got)
	if err != nil || !loaded {
		t.Fatal(loaded, err)
	}
	newTime := time.Since(start)
	if !reflect.DeepEqual(want.TrainingTreeMapping, got.TrainingTreeMapping) || !reflect.DeepEqual(want.StoryMember, got.StoryMember) {
		t.Fatal("grouped mapping or first story reward differs from previous per-owner queries")
	}
	t.Logf("%d mappings + %d story rewards: old queries %s; grouped %s", len(want.TrainingTreeMapping), len(want.StoryMember), oldTime, newTime)
}

func TestStockStartupGroupedReadsMatchEveryGLAndJPParent(t *testing.T) {
	root := os.Getenv("ELICHIKA_STOCK_STARTUP_MASTERDATA")
	if root == "" {
		t.Skip("set ELICHIKA_STOCK_STARTUP_MASTERDATA for initialized stock GL/JP comparison")
	}
	for _, region := range []string{"gl", "jp"} {
		t.Run(region, func(t *testing.T) {
			database, err := db.NewDatabase("file:" + filepath.ToSlash(filepath.Join(root, region, "masterdata.db")) + "?mode=ro")
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { database.Close() })
			var ids []int32
			var trees []*TrainingTree
			database.Do(func(session *xorm.Session) {
				err = session.Table("m_live_difficulty").Cols("live_difficulty_id").Find(&ids)
				if err == nil {
					err = session.Table("m_training_tree").Find(&trees)
				}
			})
			if err != nil {
				t.Fatal(err)
			}
			compareLiveDetails(t, database, ids)
			params := make(map[int32]int32)
			for _, tree := range trees {
				params[tree.Id] = tree.TrainingTreeCardParamMId
			}
			compareTreeDetails(t, database, params)
			compareMappingAndStoryDetails(t, database)
		})
	}
}
