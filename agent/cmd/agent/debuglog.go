package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type debugLog struct {
	mu   sync.Mutex
	f    *os.File
	path string
}

func (d *debugLog) Path() string { return d.path }

func (d *debugLog) Logf(format string, args ...interface{}) {
	if d == nil {
		return
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	line := fmt.Sprintf("[%s] %s\n", time.Now().Format("15:04:05.000"), fmt.Sprintf(format, args...))
	if d.f != nil {
		_, _ = d.f.WriteString(line)
		_ = d.f.Sync()
	}
}

func (d *debugLog) Close() {
	if d == nil || d.f == nil {
		return
	}
	_ = d.f.Close()
}

func openSetupDebugLog() *debugLog {
	dir := os.TempDir()
	if d, err := os.UserCacheDir(); err == nil {
		dir = filepath.Join(d, "ServerKit")
		_ = os.MkdirAll(dir, 0o755)
	}
	path := filepath.Join(dir, "serverkit-agent-setup.log")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return &debugLog{path: path}
	}
	return &debugLog{f: f, path: path}
}
