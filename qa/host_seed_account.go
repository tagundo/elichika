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
    "regexp"
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
    password := os.Getenv("ELICHIKA_TEST_FIXTURE_PASSWORD")
    if !regexp.MustCompile(`^[A-Za-z0-9]{16}$`).MatchString(password) { panic("fixture password must be exactly16 ASCII alphanumeric characters") }
    id := user_account.CreateNewAccount(ctx, 123456789, password)
    fmt.Printf("Synthetic playable QA account created: ID=%d; password is retained only in the private QA credential file; tutorial disabled; all default members/cards/suits/decks initialized.\n", id)
}
