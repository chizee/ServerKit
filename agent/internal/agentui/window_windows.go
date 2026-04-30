//go:build windows

package agentui

import (
	"context"
	"fmt"
	"os"
	"runtime"

	webview2 "github.com/jchv/go-webview2"

	"github.com/serverkit/agent/internal/logger"
)

// Run launches the agent's WebView2 console window and blocks until the user
// closes it. configPath is reserved for the upcoming wizard-migration
// milestone — for now the React app loads in console-only mode and the
// existing setupui wizard still owns first-run pairing.
//
// Set SERVERKIT_AGENT_UI_DEV=http://localhost:5174 to point the webview at
// the Vite dev server instead of the embedded bundle. Useful while iterating
// on the UI: changes hot-reload without rebuilding the Go binary.
func Run(ctx context.Context, log *logger.Logger, configPath string) error {
	runtime.LockOSThread()

	log.Info("agentui.Run: starting")

	// Preflight: bail with a clear error before constructing the webview.
	// Skipping this leads to "blank window" reports when the runtime is
	// missing — go-webview2 doesn't always return nil on failure.
	if v := detectWebView2(); v == "" {
		log.Error("agentui.Run: WebView2 runtime not detected")
		return fmt.Errorf(
			"WebView2 runtime not installed. " +
				"Download the Evergreen Bootstrapper from " +
				"https://developer.microsoft.com/microsoft-edge/webview2/ and re-run setup",
		)
	} else {
		log.Info("agentui.Run: WebView2 runtime detected", "version", v)
	}

	target := os.Getenv("SERVERKIT_AGENT_UI_DEV")
	var stopServer func()
	if target == "" {
		log.Info("agentui.Run: starting embedded asset server")
		url, shutdown, err := startAssetServer(ctx, log, configPath)
		if err != nil {
			log.Error("agentui.Run: asset server failed", "error", err)
			return fmt.Errorf("start asset server: %w", err)
		}
		log.Info("agentui.Run: asset server up", "url", url)
		target = url
		stopServer = shutdown
	} else {
		// Even in dev mode we still need the action/pair endpoints — the
		// Vite dev server only serves UI assets. Start the asset server
		// alongside it; dev UI fetches the local API by absolute origin.
		_, shutdown, err := startAssetServer(ctx, log, configPath)
		if err != nil {
			return fmt.Errorf("start asset server: %w", err)
		}
		stopServer = shutdown
		log.Info("agentui.Run: using dev server", "url", target)
	}
	if stopServer != nil {
		defer stopServer()
	}

	log.Info("agentui.Run: constructing WebView2 window")
	w := webview2.NewWithOptions(webview2.WebViewOptions{
		Debug:     os.Getenv("SERVERKIT_AGENT_UI_DEVTOOLS") == "true",
		AutoFocus: true,
		WindowOptions: webview2.WindowOptions{
			Title: "ServerKit Agent",
			// Sidebar is 220px; content area at 1200x800 lands at 980x800
			// which gives the Overview metric cards and the Logs/Activity
			// timeline room to breathe without horizontal scrollbars.
			Width:  1200,
			Height: 800,
			IconId: 2,
			Center: true,
		},
	})
	if w == nil {
		log.Error("agentui.Run: webview2.NewWithOptions returned nil")
		return fmt.Errorf("webview2 init failed; the runtime may be present but blocked by group policy or AV")
	}
	defer w.Destroy()

	w.SetSize(900, 600, webview2.HintMin)
	log.Info("agentui.Run: navigating", "url", target)
	w.Navigate(target)

	// Hook ctx cancellation to terminate the webview from a background
	// goroutine. Run() blocks on the OS message pump, so we need an external
	// signal to break it cleanly when the parent process is torn down.
	go func() {
		<-ctx.Done()
		log.Info("agentui.Run: ctx cancelled, terminating webview")
		w.Terminate()
	}()

	log.Info("agentui.Run: entering message loop (w.Run)")
	w.Run()
	log.Info("agentui.Run: message loop exited cleanly")
	return nil
}
