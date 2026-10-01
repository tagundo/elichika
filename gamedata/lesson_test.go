package gamedata

import (
	"elichika/db"
	"reflect"
	"testing"

	_ "modernc.org/sqlite"
	"xorm.io/xorm"
)

func lessonFixture(t *testing.T, shootingStarTable bool, shootingStarRows bool) *Lesson {
	t.Helper()
	masterdata, err := db.NewDatabase(t.TempDir() + "/masterdata.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { masterdata.Close() })
	statements := []string{
		`CREATE TABLE m_lesson_drop_amount (item_id INTEGER, count INTEGER, weight INTEGER)`,
		`INSERT INTO m_lesson_drop_amount VALUES (1, 15, 1), (2, 0, 1)`,
		`CREATE TABLE m_lesson_skill_content (skill_master_id INTEGER, rarity INTEGER, drop_type INTEGER, lesson_menu_id1 INTEGER, lesson_menu_id2 INTEGER)`,
		`INSERT INTO m_lesson_skill_content VALUES (101, 4, 2, 1, NULL), (102, 5, 3, NULL, NULL), (103, 3, 1, 2, NULL), (104, 5, 4, 2, 1)`,
		`CREATE TABLE m_lesson_skill_rarity (rarity INTEGER, weight INTEGER)`,
		`INSERT INTO m_lesson_skill_rarity VALUES (3, 120000), (4, 120000), (5, 120000)`,
		`CREATE TABLE m_lesson_skill_no_drop (has_exclusive INTEGER, weight INTEGER)`,
		`INSERT INTO m_lesson_skill_no_drop VALUES (0, 70000), (1, 20000)`,
		`CREATE TABLE m_lesson_skill_member_chance (position_id INTEGER, weight INTEGER)`,
		`INSERT INTO m_lesson_skill_member_chance VALUES (5, 1)`,
		`CREATE TABLE m_lesson_menu (id INTEGER)`,
		`INSERT INTO m_lesson_menu VALUES (1), (2), (3)`,
		`CREATE TABLE m_lesson_enhancing_item_effect_skill_drop (lesson_enhancing_item_id INTEGER, target_skill_rarity INTEGER)`,
		`INSERT INTO m_lesson_enhancing_item_effect_skill_drop VALUES (1400, 4)`,
	}
	if shootingStarTable {
		statements = append(statements, `CREATE TABLE m_lesson_skill_shooting_star (skill_master_id INTEGER, lesson_menu_id INTEGER)`)
		if shootingStarRows {
			// 101 is available from menu 1 but uses the special animation when menu 2
			// is also selected; the row for 103 must not make it available outside 222.
			statements = append(statements, `INSERT INTO m_lesson_skill_shooting_star VALUES (101, 2), (102, 3), (103, 1)`)
		}
	}
	masterdata.Do(func(session *xorm.Session) {
		for _, statement := range statements {
			if _, err = session.Exec(statement); err != nil {
				return
			}
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	g := &Gamedata{MasterdataDb: masterdata}
	if missing := missingLessonTables(g); len(missing) != 0 {
		t.Fatalf("missing required lesson tables: %v", missing)
	}
	loadLesson(g)
	if !g.Lesson.IsLoaded {
		t.Fatal("complete recovered lesson tables did not load")
	}
	return g.Lesson
}

func TestLessonShootingStarMetadataIsOptional(t *testing.T) {
	old := lessonFixture(t, false, false)
	for _, tc := range []struct {
		name string
		rows bool
	}{
		{"empty table", false},
		{"populated table", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			lesson := lessonFixture(t, true, tc.rows)
			// Animation metadata must not change eligibility, probabilities, source
			// menus, item amounts, or the skills guaranteed by an insight pin.
			if !reflect.DeepEqual(old.SkillDrop, lesson.SkillDrop) ||
				!reflect.DeepEqual(old.SkillSourceMenu, lesson.SkillSourceMenu) ||
				!reflect.DeepEqual(old.ItemAmount, lesson.ItemAmount) ||
				!reflect.DeepEqual(old.GuaranteedSkillDrop, lesson.GuaranteedSkillDrop) {
				t.Fatal("shooting-star metadata changed lesson rewards")
			}
			if !tc.rows && !reflect.DeepEqual(old.ShootingStarSkills, lesson.ShootingStarSkills) {
				t.Fatal("an empty shooting-star table changed animation metadata")
			}
		})
	}
}

func TestLessonShootingStarsRespectSelectedMenusAndEligibility(t *testing.T) {
	lesson := lessonFixture(t, true, true)
	for _, combination := range []int32{112, 121, 211, 122, 212, 221} {
		if !lesson.ShootingStarSkills[combination][101] {
			t.Errorf("skill 101 should be a shooting star for %d", combination)
		}
		if lesson.SkillSourceMenu[combination][101] != 1 {
			t.Errorf("skill 101 lost its ordinary source menu for %d", combination)
		}
	}
	if lesson.ShootingStarSkills[111][101] || lesson.ShootingStarSkills[113][101] {
		t.Error("skill 101 became a shooting star without selecting menu 2")
	}
	if _, offered := lesson.SkillSourceMenu[222][101]; offered || lesson.ShootingStarSkills[222][101] {
		t.Error("shooting-star metadata made unavailable skill 101 drop from 222")
	}
	if _, offered := lesson.SkillSourceMenu[112][103]; offered || lesson.ShootingStarSkills[112][103] {
		t.Error("shooting-star metadata bypassed skill 103's pure-menu requirement")
	}
	if !lesson.ShootingStarSkills[123][102] || lesson.SkillSourceMenu[123][102] != 0 {
		t.Error("an any-combination shooting star was not classified independently of source menu 0")
	}
	if lesson.ShootingStarSkills[111][102] {
		t.Error("an ordinary any-combination skill became a shooting star merely because its source is 0")
	}
}
