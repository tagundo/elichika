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
	"os/exec"
	"runtime"
	"strings"
	"github.com/gin-gonic/gin"
)

func cli() {
	fmt.Println("Note: cli is no longer supported!")
	fmt.Println("Note: If you want to do modification that can't be done in game, use the webUI: <your_server>/webui")
}

func main() {
    packageName1 := "com.klab.lovelive.allstars.global"
    activityName1 := "com.klab.lovelive.allstars.global.GlobalUnsafeMainActivity"
    packageName2 := "com.klab.lovelive.allstars"
    activityName2 := "com.klab.lovelive.allstars.MainActivity"

	if len(os.Args) > 1 {
		cli()
		return
	}
	userdata.Init()
	runtime.GC()
	gin.SetMode(gin.ReleaseMode)

	r := gin.Default()
	router.Router(r)
    if *config.Conf.AutorunClient == "gl" {
        // Build the shell command to start the app for "gl" case
        cmd := exec.Command("am", "start", "-n", packageName1+"/"+activityName1)

        // Execute the command
        err := cmd.Run()
        if err != nil {
            fmt.Println("Error:", err)
            return
        }
    } else if *config.Conf.AutorunClient == "jp" {
        // Build the shell command to start the app for "jp" case
        cmd := exec.Command("am", "start", "-n", packageName2+"/"+activityName2)

        // Execute the command
        err := cmd.Run()
        if err != nil {
            fmt.Println("Error:", err)
            return
        }
    } else {
        fmt.Println("Unknown configuration value for AutorunClient.")
    }
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