package user

import (
	"elichika/config"
	"elichika/nativeaccess"
	"elichika/router"

	"fmt"
	"net/http"
	"sort"

	"github.com/gin-gonic/gin"
)

type UserFeature struct {
	Name string
	Path string
}

func (uf *UserFeature) GetButtonString() string {
	return fmt.Sprintf(`<div><button onclick="location.href='%s'+window.location.search" type="button">%s</button></div>`, uf.Path, uf.Name)
}

var (
	featuresBody *string
	features     []UserFeature
)

// each features will be a button to jump to that features
func addFeature(name, path string) {
	features = append(features, UserFeature{
		Name: name,
		Path: path,
	})
}

func init() {
	router.AddTemplates(config.RootPath + "webui/user/logged_in_user.html")
	router.AddHandler("/webui/user", "GET", "/", func(ctx *gin.Context) {
		if featuresBody == nil {
			featuresBody = new(string)
			*featuresBody = ""
			sort.Slice(features, func(i, j int) bool {
				return features[i].Name < features[j].Name
			})
			for i := range features {
				*featuresBody += features[i].GetButtonString() + "\n"
			}
		}
		body := *featuresBody
		if nativeaccess.Authorized(ctx) {
			body = `<div><button onclick="location.href='client_connection'+window.location.search" data-native-text="Client login / migration">Client login / migration</button></div>` + body + `<script src="/webui/native_local.js"></script><script>document.body.dataset.elichikaLocalAccess='true';apply_native_language()</script>`
		}
		ctx.HTML(http.StatusOK, "logged_in_user.html", gin.H{
			"body": body,
		})
	})

}
