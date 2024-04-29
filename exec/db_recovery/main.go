package main

import (
	"elichika/exec/db_recovery/table"

	"os"
)

func main() {
	if len(os.Args) < 2 {
		return
	}
	output := table.Run(os.Args[1])
	if len(os.Args) >= 3 {
		os.WriteFile(os.Args[2], []byte(output), 0777)
	} else {
	}

}
