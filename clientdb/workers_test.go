package clientdb

import (
	"errors"
	"fmt"
	"os"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
)

func TestClientDBWorkerResourcePolicy(t *testing.T) {
	for _, test := range []struct {
		jobs, cpus int
		memory     uint64
		known      bool
		want       int
	}{
		{0, 8, 8 << 30, true, 0}, {20, 8, 8 << 30, false, 1},
		{20, 1, 8 << 30, true, 1}, {20, 8, 512<<20 - 1, true, 1},
		{20, 2, 512 << 20, true, 2}, {20, 8, 1<<30 - 1, true, 2},
		{20, 4, 1 << 30, true, 4}, {20, 8, 2<<30 - 1, true, 4},
		{20, 8, 2 << 30, true, 8}, {3, 128, 64 << 30, true, 3},
	} {
		if got := clientDBWorkerLimit(test.jobs, test.cpus, test.memory, test.known); got != test.want {
			t.Fatalf("policy %+v: got %d", test, got)
		}
	}
	for _, invalid := range []string{"", "-1", "+2147483648", " 2147483648", "2147483648\n", "1GiB", "18446744073709551616"} {
		if got := clientDBDarwinWorkerCount(50, 32, invalid); got != 1 {
			t.Fatalf("invalid Mach snapshot %q enabled %d workers", invalid, got)
		}
	}
	if got := clientDBDarwinWorkerCount(50, 8, "2147483648"); got != 8 {
		t.Fatalf("valid Mach snapshot: %d workers", got)
	}
}

func clientDBTestFiles(files map[string]string) func(string) ([]byte, error) {
	return func(name string) ([]byte, error) {
		if value, ok := files[name]; ok {
			return []byte(value), nil
		}
		return nil, &os.PathError{Op: "open", Path: name, Err: os.ErrNotExist}
	}
}

func TestClientDBMemoryPolicyHonorsCgroupAncestors(t *testing.T) {
	files := map[string]string{
		"/proc/meminfo":                              "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n",
		"/proc/self/cgroup":                          "0::/parent/child\n",
		"/sys/fs/cgroup/memory.max":                  "max\n",
		"/sys/fs/cgroup/memory.high":                 "max\n",
		"/sys/fs/cgroup/parent/memory.max":           "1073741824\n",
		"/sys/fs/cgroup/parent/memory.current":       "536870912\n",
		"/sys/fs/cgroup/parent/child/memory.max":     "2147483648\n",
		"/sys/fs/cgroup/parent/child/memory.high":    "max\n",
		"/sys/fs/cgroup/parent/child/memory.current": "134217728\n",
	}
	if available, known := clientDBMemoryAvailable(clientDBTestFiles(files)); !known || available != 512<<20 {
		t.Fatalf("ignored stricter parent cgroup: %d %v", available, known)
	}
	files["/sys/fs/cgroup/parent/memory.high"] = "603979776\n"
	if available, known := clientDBMemoryAvailable(clientDBTestFiles(files)); !known || available != 64<<20 {
		t.Fatalf("ignored memory.high: %d %v", available, known)
	}
	files["/sys/fs/cgroup/parent/memory.current"] = "1073741825\n"
	if available, known := clientDBMemoryAvailable(clientDBTestFiles(files)); !known || available != 0 {
		t.Fatalf("exhausted cgroup not zero: %d %v", available, known)
	}
	delete(files, "/sys/fs/cgroup/parent/memory.current")
	if _, known := clientDBMemoryAvailable(clientDBTestFiles(files)); known {
		t.Fatal("accepted finite cgroup limit without current usage")
	}
}

func TestClientDBMemoryPolicyLegacyAndInvalidInputs(t *testing.T) {
	files := map[string]string{
		"/proc/meminfo":     "MemAvailable: 8388608 kB\n",
		"/proc/self/cgroup": "3:memory:/parent/child\n",
		"/sys/fs/cgroup/memory/memory.limit_in_bytes":        "9223372036854771712\n",
		"/sys/fs/cgroup/memory/parent/memory.limit_in_bytes": "1073741824\n",
		"/sys/fs/cgroup/memory/parent/memory.usage_in_bytes": "268435456\n",
	}
	if available, known := clientDBMemoryAvailable(clientDBTestFiles(files)); !known || available != 768<<20 {
		t.Fatalf("legacy cgroup: %d %v", available, known)
	}
	for _, invalid := range []string{"", "MemAvailable: -1 kB", "MemAvailable: 18446744073709551615 kB", "MemAvailable: 123 MB"} {
		files["/proc/meminfo"] = invalid
		if _, known := clientDBMemoryAvailable(clientDBTestFiles(files)); known {
			t.Fatalf("accepted invalid meminfo %q", invalid)
		}
	}
	files["/proc/meminfo"] = "MemAvailable: 8388608 kB\n"
	files["/sys/fs/cgroup/memory/parent/memory.limit_in_bytes"] = "invalid"
	if _, known := clientDBMemoryAvailable(clientDBTestFiles(files)); known {
		t.Fatal("accepted malformed cgroup limit")
	}
}

func TestClientDBCPUQuotaHonorsParent(t *testing.T) {
	files := map[string]string{
		"/proc/self/cgroup":                   "0::/parent/child\n",
		"/sys/fs/cgroup/cpu.max":              "max 100000\n",
		"/sys/fs/cgroup/parent/cpu.max":       "250000 100000\n",
		"/sys/fs/cgroup/parent/child/cpu.max": "800000 100000\n",
	}
	if got := clientDBCPUQuota(clientDBTestFiles(files)); got != 2 {
		t.Fatalf("ignored parent CPU quota: %d", got)
	}
	for _, invalid := range []string{"bad", "1000 0", "-1 1000"} {
		files["/sys/fs/cgroup/parent/cpu.max"] = invalid
		if got := clientDBCPUQuota(clientDBTestFiles(files)); got != 1 {
			t.Fatalf("malformed CPU quota %q: %d", invalid, got)
		}
	}
}

func TestClientDBWorkersBoundConcurrencyAndVisitEveryJobOnce(t *testing.T) {
	started, release, done := make(chan struct{}, 4), make(chan struct{}), make(chan error, 1)
	var active, maximum atomic.Int32
	visits := make([]int, 17)
	go func() {
		done <- runClientDBJobs(len(visits), 4, func(index int) error {
			current := active.Add(1)
			for old := maximum.Load(); old < current; old = maximum.Load() {
				if maximum.CompareAndSwap(old, current) {
					break
				}
			}
			if index < 4 {
				started <- struct{}{}
				<-release
			}
			visits[index]++
			active.Add(-1)
			return nil
		})
	}()
	for index := 0; index < 4; index++ {
		<-started
	}
	if maximum.Load() != 4 {
		t.Fatal("did not run four independent workers")
	}
	close(release)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	for index, count := range visits {
		if count != 1 {
			t.Fatalf("job %d visited %d times", index, count)
		}
	}
	if active.Load() != 0 || maximum.Load() > 4 {
		t.Fatal("worker limit violated")
	}
}

func TestClientDBWorkersJoinAfterErrorAndRecoverPanic(t *testing.T) {
	for _, failure := range []string{"error", "panic", "nil-panic", "goexit"} {
		t.Run(failure, func(t *testing.T) {
			started, failed, release := make(chan struct{}), make(chan struct{}), make(chan struct{})
			done := make(chan error, 1)
			go func() {
				done <- runClientDBJobs(2, 2, func(index int) error {
					if index == 0 {
						close(started)
						<-release
						return nil
					}
					close(failed)
					switch failure {
					case "panic":
						panic("synthetic worker failure")
					case "nil-panic":
						panic(nil)
					case "goexit":
						runtime.Goexit()
					}
					return errors.New("synthetic worker failure")
				})
			}()
			<-started
			<-failed
			select {
			case err := <-done:
				t.Fatalf("returned before another worker joined: %v", err)
			default:
			}
			close(release)
			if err := <-done; err == nil {
				t.Fatal("worker failure was swallowed")
			}
		})
	}
}

func TestClientDBWorkersRejectInvalidRequests(t *testing.T) {
	for _, request := range [][2]int{{-1, 1}, {1, 0}, {1, 9}, {1, -1}} {
		if err := runClientDBJobs(request[0], request[1], func(int) error { return nil }); err == nil {
			t.Fatalf("accepted request %v", request)
		}
	}
	if err := runClientDBJobs(1, 1, nil); err == nil {
		t.Fatal("accepted nil action")
	}
	if err := runClientDBJobs(0, 0, nil); err != nil {
		t.Fatal(err)
	}
	err := runClientDBJobs(8, 4, func(index int) error { return fmt.Errorf("failure %d", index) })
	if err == nil || !strings.Contains(err.Error(), "failure 0") {
		t.Fatalf("unstable error order: %v", err)
	}
}
