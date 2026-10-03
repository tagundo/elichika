package gamedata

import (
	"elichika/db"
	"elichika/generic/drop"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"xorm.io/xorm"
)

func lessonPoolWeights(pool *drop.WeightedDropList[int32]) map[int32]int64 {
	result := map[int32]int64{}
	if pool == nil {
		return result
	}
	v := reflect.ValueOf(pool).Elem()
	previous := int64(0)
	for i := 0; i < v.FieldByName("contents").Len(); i++ {
		cumulative := v.FieldByName("weights").Index(i).Int()
		result[int32(v.FieldByName("contents").Index(i).Int())] = cumulative - previous
		previous = cumulative
	}
	return result
}

func TestLessonFirstSkillPoolsPreservePositiveWeightsAndExcludeSpecialActions(t *testing.T) {
	lesson := lessonFixture(t, true, true)
	for recipe, ordinary := range lesson.FirstSkillDrop {
		normal := lessonPoolWeights(lesson.SkillDrop[recipe])
		for skill, weight := range lessonPoolWeights(ordinary) {
			if skill <= 0 || weight <= 0 || weight != normal[skill] || lesson.ShootingStarSkills[recipe][skill] {
				t.Fatalf("invalid first-skill weighted candidate: recipe=%d skill=%d weight=%d normal=%d", recipe, skill, weight, normal[skill])
			}
			if _, exists := lesson.SkillSourceMenu[recipe][skill]; !exists {
				t.Fatal("candidate lost its eligible source-menu metadata")
			}
		}
	}
	if _, exists := lessonPoolWeights(lesson.FirstSkillDrop[112])[101]; exists {
		t.Fatal("first guide fallback must not synthesize a Shooting Star")
	}
	if lessonPoolWeights(lesson.FirstSkillDrop[111])[101] <= 0 {
		t.Fatal("the same skill should remain an ordinary fallback without its star menu")
	}
	if lesson.FirstSkillLegacyDrop != nil {
		t.Fatal("the only any-combination skill has a star mapping and must not repair a recipe-less result")
	}
}

func TestLessonLegacyFirstSkillPoolUsesKnownUniversallyOrdinarySkills(t *testing.T) {
	g := lessonDatabaseFixture(t, true, true)
	var setupErr error
	g.MasterdataDb.Do(func(session *xorm.Session) {
		for _, sql := range []string{
			`INSERT INTO m_lesson_skill_content VALUES (105, 3, 3, NULL, NULL), (106, 3, 3, NULL, NULL), (107, 3, 3, 99, NULL)`,
			`INSERT INTO m_passive_skill VALUES (105),(107)`,
		} {
			if _, setupErr = session.Exec(sql); setupErr != nil {
				return
			}
		}
	})
	if setupErr != nil {
		t.Fatal(setupErr)
	}
	loadLesson(g)
	want := map[int32]int64{105: 120000}
	if got := lessonPoolWeights(g.Lesson.FirstSkillLegacyDrop); !reflect.DeepEqual(got, want) {
		t.Fatalf("legacy result must use a known universal ordinary skill: got %v want %v", got, want)
	}
	for recipe, pool := range g.Lesson.FirstSkillDrop {
		for skill := range lessonPoolWeights(pool) {
			if skill == 106 || skill == 107 {
				t.Fatalf("unknown ID or invalid source entered recipe %d", recipe)
			}
		}
	}
}

func TestLessonFirstSkillPoolDoesNotRollFromZeroWeightOrMissingMetadata(t *testing.T) {
	for _, sql := range []string{`UPDATE m_lesson_skill_rarity SET weight=0`, `DROP TABLE m_passive_skill`} {
		t.Run(sql, func(t *testing.T) {
			g := lessonDatabaseFixture(t, true, true)
			var setupErr error
			g.MasterdataDb.Do(func(session *xorm.Session) { _, setupErr = session.Exec(sql) })
			if setupErr != nil {
				t.Fatal(setupErr)
			}
			loadLesson(g)
			if len(g.Lesson.FirstSkillDrop) != 0 || g.Lesson.FirstSkillLegacyDrop != nil {
				t.Fatal("zero-only or missing-client metadata must leave the fallback unavailable")
			}
		})
	}
}

func TestLessonWeightsRejectExactInt32Overflow(t *testing.T) {
	g := lessonDatabaseFixture(t, false, false)
	var setupErr error
	g.MasterdataDb.Do(func(session *xorm.Session) {
		_, setupErr = session.Exec(`UPDATE m_lesson_skill_no_drop SET weight=?`, math.MaxInt32)
		if setupErr == nil {
			_, setupErr = session.Exec(`UPDATE m_lesson_skill_rarity SET weight=1`)
		}
	})
	if setupErr != nil {
		t.Fatal(setupErr)
	}
	defer func() {
		got := recover()
		if got == nil || !strings.Contains(got.(string), "lesson skill weights must be nonnegative and total at most MaxInt32") {
			t.Fatalf("exact MaxInt32+1 must fail before the historical AddItem bound lets it wrap: %v", got)
		}
	}()
	loadLesson(g)
}

func TestStockLessonFirstSkillPoolsForEveryGLAndJPRecipe(t *testing.T) {
	root := os.Getenv("ELICHIKA_STOCK_LESSON_MASTERDATA")
	if root == "" {
		t.Skip("set ELICHIKA_STOCK_LESSON_MASTERDATA to validate initialized stock GL/JP assets")
	}
	for _, region := range []string{"gl", "jp"} {
		t.Run(region, func(t *testing.T) {
			master, err := db.NewDatabase(filepath.Join(root, region, "masterdata.db"))
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { master.Close() })
			g := &Gamedata{MasterdataDb: master}
			loadLesson(g)
			if !g.Lesson.IsLoaded || len(g.Lesson.FirstSkillDrop) != len(g.Lesson.SkillDrop) || g.Lesson.FirstSkillLegacyDrop == nil {
				t.Fatalf("every stock recipe must support a first guide: loaded=%v fallback=%d recipes=%d", g.Lesson.IsLoaded, len(g.Lesson.FirstSkillDrop), len(g.Lesson.SkillDrop))
			}
			for recipe, pool := range g.Lesson.FirstSkillDrop {
				normal := lessonPoolWeights(g.Lesson.SkillDrop[recipe])
				for skill, weight := range lessonPoolWeights(pool) {
					if skill <= 0 || weight <= 0 || weight != normal[skill] || g.Lesson.ShootingStarSkills[recipe][skill] {
						t.Fatalf("stock weighted ordinary candidate invalid: recipe=%d skill=%d", recipe, skill)
					}
					source, exists := g.Lesson.SkillSourceMenu[recipe][skill]
					if !exists || (source != 0 && source != recipe/100 && source != recipe/10%10 && source != recipe%10) {
						t.Fatalf("stock candidate source invalid: recipe=%d skill=%d source=%d", recipe, skill, source)
					}
				}
			}
			for skill := range lessonPoolWeights(g.Lesson.FirstSkillLegacyDrop) {
				for recipe := range g.Lesson.SkillDrop {
					if _, exists := g.Lesson.SkillSourceMenu[recipe][skill]; !exists || g.Lesson.ShootingStarSkills[recipe][skill] {
						t.Fatalf("legacy skill %d is not ordinary and universally eligible at recipe %d", skill, recipe)
					}
				}
			}
			t.Logf("validated %d stock recipes and legacy pool %v", len(g.Lesson.SkillDrop), lessonPoolWeights(g.Lesson.FirstSkillLegacyDrop))
		})
	}
}
