//go:build !embedded

package main

import (
	"context"
	"elichika/managementmode"
	"elichika/router"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
)

// This process has one role. It never binds the configured game-server address.
func serveManagement() error {
	defer managementmode.Release()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return err
	}
	defer listener.Close()
	origin := "http://" + listener.Addr().String()
	r := gin.New()
	r.Use(gin.Recovery(), managementmode.Boundary(origin))
	router.ManagementRouter(r)
	server := &http.Server{Handler: r, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second}
	finished := make(chan error, 1)
	go func() { finished <- server.Serve(listener) }()
	ready, _ := json.Marshal(map[string]any{"url": origin, "pid": os.Getpid()})
	// The parent already owns the readiness nonce; never print it into logs.
	fmt.Println("ELICHIKA_MANAGEMENT_READY " + string(ready))
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(stop)
	parentGone := managementParentGone(os.Getenv("ELICHIKA_MANAGEMENT_PARENT_PID"))
	select {
	case err := <-finished:
		if err != http.ErrServerClosed {
			return err
		}
	case <-stop:
	case <-parentGone:
	}
	// Drain existing authenticated writes before the host takes its DB lease.
	return server.Shutdown(context.Background())
}

func managementParentGone(value string) <-chan struct{} {
	gone := make(chan struct{})
	parent, err := strconv.Atoi(value)
	if err != nil || parent <= 1 {
		return gone
	}
	go func() {
		ticker := time.NewTicker(250 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			if os.Getppid() != parent {
				close(gone)
				return
			}
		}
	}()
	return gone
}
