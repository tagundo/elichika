// Synthetic playable QA account only. Build from Elichika's module directory;
// execute in an explicitly marked disposable initialized runtime, never real data.
package main

import (
    "elichika/config"
    "elichika/locale"
    "elichika/subsystem/user_account"
    "elichika/userdata"
    "fmt"
    "os"
    "path/filepath"

    "github.com/gin-gonic/gin"
)

func main() {
    cwd, err := os.Getwd()
    if err != nil { panic(err) }
    wanted, err := filepath.Abs(os.Getenv("ELICHIKA_TEST_RUNTIME"))
    if err != nil || os.Getenv("ELICHIKA_TEST_RUNTIME") == "" || wanted != cwd { panic("requires exact disposable ELICHIKA_TEST_RUNTIME working directory") }
    userdata.Init()
    count, err := userdata.Engine.Table("u_status").Count()
    if err != nil || count != 0 { panic("refusing to seed a database that already has any accounts") }
    tutorial := false
    config.Conf.Tutorial = &tutorial
    language := os.Getenv("ELICHIKA_TEST_FIXTURE_LANGUAGE")
    if language == "" { language = "en" }
    local, ok := locale.Locales[language]
    if !ok { panic("unknown fixture language") }
    ctx, _ := gin.CreateTestContext(nil)
    ctx.Set("gamedata", local.Gamedata)
    ctx.Set("dictionary", local.Dictionary)
    ctx.Set("locale", local)
    id := user_account.CreateNewAccount(ctx, 123456789, "SifasQa123456789")
    fmt.Printf("Synthetic playable QA account created: ID=%d; password is the documented fixture value; tutorial disabled; all default members/cards/suits/decks initialized.\n", id)
}
