package clientdb

import (
	"fmt"
	"os"
	"path"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
)

const clientDBMaxWorkers = 8

// Memory is a whole-process safety budget, not a claim that each streamed job
// needs hundreds of MiB. Leave room for the host app and other processes.
func clientDBWorkerLimit(jobs, cpus int, available uint64, known bool) int {
	if jobs <= 0 {
		return 0
	}
	workers := 1
	if known && cpus >= 2 && available >= 512<<20 {
		workers = 2
	}
	if known && cpus >= 4 && available >= 1<<30 {
		workers = 4
	}
	if known && cpus >= 8 && available >= 2<<30 {
		workers = 8
	}
	if workers > jobs {
		workers = jobs
	}
	return workers
}

func clientDBWorkerCount(jobs int) int {
	cpus := runtime.NumCPU()
	if maximum := runtime.GOMAXPROCS(0); maximum < cpus {
		cpus = maximum
	}
	if runtime.GOOS == "darwin" {
		// The native wrapper provides a Mach available-memory snapshot. Never
		// infer available memory from physical RAM or a user-facing setting.
		return clientDBDarwinWorkerCount(jobs, cpus, os.Getenv("ELICHIKA_CLIENTDB_MEMORY_BYTES"))
	}
	if runtime.GOOS != "linux" && runtime.GOOS != "android" {
		return clientDBWorkerLimit(jobs, cpus, 0, false)
	}
	if quota := clientDBCPUQuota(os.ReadFile); quota > 0 && quota < cpus {
		cpus = quota
	}
	available, known := clientDBMemoryAvailable(os.ReadFile)
	return clientDBWorkerLimit(jobs, cpus, available, known)
}

func clientDBDarwinWorkerCount(jobs, cpus int, snapshot string) int {
	if snapshot == "" {
		return clientDBWorkerLimit(jobs, cpus, 0, false)
	}
	for _, digit := range snapshot {
		if digit < '0' || digit > '9' {
			return clientDBWorkerLimit(jobs, cpus, 0, false)
		}
	}
	available, err := strconv.ParseUint(snapshot, 10, 64)
	return clientDBWorkerLimit(jobs, cpus, available, err == nil)
}

// Include every readable ancestor: a nested process can have a looser local
// limit than its parent. Never follow a path outside the cgroup mount.
func clientDBCgroupDirectories(read func(string) ([]byte, error)) (v2, v1 []string) {
	v2, v1 = []string{"/sys/fs/cgroup"}, []string{"/sys/fs/cgroup/memory"}
	data, err := read("/proc/self/cgroup")
	if err != nil {
		return
	}
	appendAncestors := func(values []string, root, relative string) []string {
		relative = path.Clean(strings.TrimPrefix(relative, "/"))
		if relative == ".." || strings.HasPrefix(relative, "../") {
			return values
		}
		for current := path.Join(root, relative); current != root; current = path.Dir(current) {
			values = append(values, current)
		}
		return values
	}
	for _, line := range strings.Split(string(data), "\n") {
		parts := strings.SplitN(line, ":", 3)
		if len(parts) != 3 {
			continue
		}
		if parts[0] == "0" && parts[1] == "" {
			v2 = appendAncestors(v2, "/sys/fs/cgroup", parts[2])
		}
		for _, controller := range strings.Split(parts[1], ",") {
			if controller == "memory" {
				v1 = appendAncestors(v1, "/sys/fs/cgroup/memory", parts[2])
			}
		}
	}
	return
}

func clientDBMemoryAvailable(read func(string) ([]byte, error)) (uint64, bool) {
	data, err := read("/proc/meminfo")
	if err != nil {
		return 0, false
	}
	var available uint64
	found := false
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 3 && fields[0] == "MemAvailable:" && fields[2] == "kB" {
			value, err := strconv.ParseUint(fields[1], 10, 64)
			if err != nil || value > ^uint64(0)/1024 {
				return 0, false
			}
			available, found = value*1024, true
			break
		}
	}
	if !found {
		return 0, false
	}
	v2, v1 := clientDBCgroupDirectories(read)
	apply := func(directory, limitName, currentName string, legacy bool) bool {
		limitData, err := read(path.Join(directory, limitName))
		if os.IsNotExist(err) {
			return true
		}
		if err != nil {
			return false
		}
		text := strings.TrimSpace(string(limitData))
		if text == "max" {
			return true
		}
		limit, err := strconv.ParseUint(text, 10, 64)
		if err != nil {
			return false
		}
		if legacy && limit >= 1<<60 { // Linux v1's unlimited sentinel.
			return true
		}
		currentData, err := read(path.Join(directory, currentName))
		if err != nil {
			return false
		}
		current, err := strconv.ParseUint(strings.TrimSpace(string(currentData)), 10, 64)
		if err != nil {
			return false
		}
		remaining := uint64(0)
		if current < limit {
			remaining = limit - current
		}
		if remaining < available {
			available = remaining
		}
		return true
	}
	for _, directory := range v2 {
		for _, name := range []string{"memory.max", "memory.high"} {
			if !apply(directory, name, "memory.current", false) {
				return 0, false
			}
		}
	}
	for _, directory := range v1 {
		if !apply(directory, "memory.limit_in_bytes", "memory.usage_in_bytes", true) {
			return 0, false
		}
	}
	return available, true
}

func clientDBCPUQuota(read func(string) ([]byte, error)) int {
	directories, _ := clientDBCgroupDirectories(read)
	minimum := 0
	for _, directory := range directories {
		data, err := read(path.Join(directory, "cpu.max"))
		if err != nil {
			continue
		}
		fields := strings.Fields(string(data))
		if len(fields) != 2 {
			return 1
		}
		if fields[0] == "max" {
			continue
		}
		quota, first := strconv.ParseUint(fields[0], 10, 64)
		period, second := strconv.ParseUint(fields[1], 10, 64)
		if first != nil || second != nil || period == 0 {
			return 1
		}
		cpus := quota / period
		if cpus < 1 {
			cpus = 1
		}
		if cpus > clientDBMaxWorkers {
			cpus = clientDBMaxWorkers
		}
		if minimum == 0 || int(cpus) < minimum {
			minimum = int(cpus)
		}
	}
	return minimum
}

func clientDBJob(index int, action func(int) error) (err error) {
	returned := false
	defer func() {
		if !returned {
			err = fmt.Errorf("client database worker %d panicked: %v", index, recover())
		}
	}()
	err = action(index)
	returned = true
	return
}

// Workers only prepare independent output files. Join every worker, even after
// an error, so no goroutine can keep writing after the caller refuses headers.
func runClientDBJobs(jobs, workers int, action func(int) error) error {
	if jobs < 0 || workers < 0 || workers > clientDBMaxWorkers || (jobs > 0 && (workers == 0 || action == nil)) {
		return fmt.Errorf("invalid client database worker request")
	}
	if jobs == 0 {
		return nil
	}
	if workers > jobs {
		workers = jobs
	}
	results, finished := make([]error, jobs), make([]bool, jobs)
	var next atomic.Int64
	var group sync.WaitGroup
	for worker := 0; worker < workers; worker++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for index := int(next.Add(1)) - 1; index < jobs; index = int(next.Add(1)) - 1 {
				results[index] = clientDBJob(index, action)
				finished[index] = true
			}
		}()
	}
	group.Wait()
	for index, err := range results {
		if !finished[index] {
			return fmt.Errorf("client database worker %d did not finish", index)
		}
		if err != nil {
			return err
		}
	}
	return nil
}
