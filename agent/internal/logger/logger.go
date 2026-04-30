package logger

import (
	"io"
	"os"
	"path/filepath"

	"github.com/serverkit/agent/internal/config"
	"gopkg.in/natefinch/lumberjack.v2"
	"log/slog"
)

// Logger wraps slog.Logger with additional context
type Logger struct {
	*slog.Logger
	// rotator is the lumberjack writer when file logging is enabled. Nil
	// when only stdout is configured. Exposed via Rotate() so the desktop
	// console's Logs-tab "Clear" button can roll the file without racing
	// the live writer.
	rotator *lumberjack.Logger
}

// New creates a new logger with the given configuration
func New(cfg config.LoggingConfig) *Logger {
	var level slog.Level
	switch cfg.Level {
	case "debug":
		level = slog.LevelDebug
	case "info":
		level = slog.LevelInfo
	case "warn":
		level = slog.LevelWarn
	case "error":
		level = slog.LevelError
	default:
		level = slog.LevelInfo
	}

	opts := &slog.HandlerOptions{
		Level: level,
	}

	var writers []io.Writer

	// Always write to stdout
	writers = append(writers, os.Stdout)

	// Also write to file if configured
	var rotator *lumberjack.Logger
	if cfg.File != "" {
		// Ensure log directory exists
		dir := filepath.Dir(cfg.File)
		if err := os.MkdirAll(dir, 0755); err == nil {
			// Use lumberjack for log rotation
			rotator = &lumberjack.Logger{
				Filename:   cfg.File,
				MaxSize:    cfg.MaxSize, // megabytes
				MaxBackups: cfg.MaxBackups,
				MaxAge:     cfg.MaxAge, // days
				Compress:   cfg.Compress,
			}
			writers = append(writers, rotator)
		}
	}

	// Create multi-writer
	multiWriter := io.MultiWriter(writers...)

	handler := slog.NewJSONHandler(multiWriter, opts)
	logger := slog.New(handler)

	return &Logger{Logger: logger, rotator: rotator}
}

// Rotate triggers a manual log rotation. No-op when file logging is
// disabled. Used by the desktop console's "Clear logs" button so the live
// writer flushes to a backup before the in-memory tail clears.
func (l *Logger) Rotate() error {
	if l.rotator == nil {
		return nil
	}
	return l.rotator.Rotate()
}

// With returns a new logger with additional attributes. Carries the rotator
// reference so component loggers can also trigger rotation if needed.
func (l *Logger) With(args ...any) *Logger {
	return &Logger{Logger: l.Logger.With(args...), rotator: l.rotator}
}

// WithComponent returns a logger with a component name
func (l *Logger) WithComponent(name string) *Logger {
	return l.With("component", name)
}
