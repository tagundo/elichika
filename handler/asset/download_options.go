package asset

import (
	"elichika/assetdata"

	"flag"
	"fmt"
	"io"
	"strconv"
	"strings"
)

// DownloadOptions keeps the legacy positional worker count while allowing an
// explicitly scoped download. A command with no flags retains the legacy union.
type DownloadOptions struct {
	Workers   int
	Selection assetdata.DownloadSelection
	Scoped    bool
}

func ParseDownloadOptions(args []string) (DownloadOptions, error) {
	options := DownloadOptions{Workers: 8}
	if len(args) != 0 && !strings.HasPrefix(args[0], "--") {
		workers, err := strconv.Atoi(args[0])
		if err != nil || workers < 1 {
			return options, fmt.Errorf("invalid worker count %q: use a positive integer", args[0])
		}
		options.Workers = workers
		args = args[1:]
	}
	options.Scoped = len(args) != 0
	flags := flag.NewFlagSet("download_packs", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	region := flags.String("region", "both", "gl, jp or both")
	platform := flags.String("platform", "both", "android, ios or both")
	language := flags.String("language", "all", "all, en, ko, zh or ja")
	if err := flags.Parse(args); err != nil {
		return options, err
	}
	if flags.NArg() != 0 {
		return options, fmt.Errorf("unexpected download_packs argument %q", flags.Arg(0))
	}
	options.Selection = assetdata.DownloadSelection{
		Region: assetdata.Region(*region), Platform: assetdata.Platform(*platform), Language: assetdata.Language(*language),
	}
	if *region == "" || *platform == "" || *language == "" {
		return options, fmt.Errorf("download scope flags require non-empty values")
	}
	return options, options.Selection.Validate()
}
