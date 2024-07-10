package main

import (
	"elichika/config"
	_ "elichika/handler"
	_ "elichika/subsystem"
	"elichika/userdata"
	_ "elichika/webui"
	"elichika/router"
	"bufio"
	"fmt"
	"os"
	"runtime"
	"strings"
	"github.com/gin-gonic/gin"
)

func cli() {
	fmt.Println("CLI is reserved for special behaviour, the server will now exit, start it again without any argument!")
}

func main() {
	if len(os.Args) > 1 {
		cli()
		return
	}
	userdata.Init()
	runtime.GC()
	gin.SetMode(gin.ReleaseMode)

	r := gin.Default()
	router.Router(r)
	fmt.Println("server address: ", *config.Conf.ServerAddress)
	fmt.Println("WebUI address: ", *config.Conf.ServerAddress+"/webui")
	fmt.Println("Type 'exit' to close the program.")

	// Start a goroutine to handle user input concurrently
	go func() {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			input := scanner.Text()
			if strings.ToLower(input) == "exit" {
				// You can perform any cleanup or additional actions here before exiting
				fmt.Println("Closing the program...")
				os.Exit(0)
			} else {
				fmt.Println("Unknown command. Type 'exit' to close the program.")
			}
		}
	}()

	r.Run(*config.Conf.ServerAddress)
}