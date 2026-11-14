package asset

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Keep directory identities rather than trusting a one-time basename map. A
// download/extraction changes its parent directory, so a miss can discover new
// nested files without rescanning every pack on every HTTP request.
type packDirectoryState struct {
	path string
	info os.FileInfo
}

type packIndexProblem struct {
	path string
	err  error
}

func regularPackFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

// scanPackFiles follows the owner's directory links, including an external
// asset library, but visits each resolved directory once to stop link cycles.
// Only regular files are indexed: directories and dangling/special files must
// not be mistaken for downloadable game packs.
func scanPackFiles(root string) (map[string]string, []packDirectoryState, []packIndexProblem) {
	files := make(map[string]string)
	directories := []packDirectoryState{}
	problems := []packIndexProblem{}
	seen := make(map[string]bool)
	var walk func(string)
	walk = func(path string) {
		resolved, err := filepath.EvalSymlinks(path)
		if err != nil {
			problems = append(problems, packIndexProblem{path, err})
			return
		}
		resolved, err = filepath.Abs(resolved)
		if err != nil {
			problems = append(problems, packIndexProblem{path, err})
			return
		}
		if seen[resolved] {
			return
		}
		seen[resolved] = true
		info, err := os.Stat(path)
		if err != nil {
			problems = append(problems, packIndexProblem{path, err})
			return
		}
		if !info.IsDir() {
			problems = append(problems, packIndexProblem{path, fmt.Errorf("pack library path is not a directory")})
			return
		}
		directories = append(directories, packDirectoryState{path, info})
		entries, err := os.ReadDir(path)
		if err != nil {
			problems = append(problems, packIndexProblem{path, err})
			return
		}
		for _, entry := range entries {
			child := filepath.Join(path, entry.Name())
			if entry.IsDir() {
				walk(child)
				continue
			}
			kind := entry.Type()
			if kind&os.ModeSymlink != 0 {
				info, err := os.Stat(child)
				if err != nil {
					problems = append(problems, packIndexProblem{child, err})
					continue
				}
				if info.IsDir() {
					walk(child)
					continue
				}
				if !info.Mode().IsRegular() {
					continue
				}
			} else if kind != 0 {
				continue
			}
			// ReadDir already supplies the type for ordinary entries. Do not add
			// one Stat call per pack during a large scan; lookup performs the
			// final regular-file check before returning any downloadable path.
			if strings.HasPrefix(entry.Name(), ".") {
				continue
			}
			files[entry.Name()] = child
		}
	}
	walk(root)
	return files, directories, problems
}

func packDirectoriesChanged(directories []packDirectoryState) bool {
	if len(directories) == 0 {
		return true
	}
	for _, previous := range directories {
		current, err := os.Stat(previous.path)
		if err != nil || !current.IsDir() || !os.SameFile(previous.info, current) ||
			current.Mode() != previous.info.Mode() || !current.ModTime().Equal(previous.info.ModTime()) {
			return true
		}
	}
	return false
}
