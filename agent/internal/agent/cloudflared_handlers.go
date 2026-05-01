package agent

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/serverkit/agent/internal/cloudflared"
)

// Handlers for cloudflared:* actions. Same shape as cron handlers:
// thin parse + dispatch. Validation lives in the cloudflared package.

func (a *Agent) handleCloudflaredStatus(ctx context.Context, _ json.RawMessage) (interface{}, error) {
	return a.cloudflared.Status(ctx)
}

func (a *Agent) handleCloudflaredTunnelList(ctx context.Context, _ json.RawMessage) (interface{}, error) {
	tunnels, err := a.cloudflared.List(ctx)
	if err != nil {
		return nil, err
	}
	if tunnels == nil {
		tunnels = []cloudflared.Tunnel{}
	}
	return map[string]interface{}{"tunnels": tunnels}, nil
}

func (a *Agent) handleCloudflaredTunnelCreate(ctx context.Context, params json.RawMessage) (interface{}, error) {
	var req cloudflared.CreateRequest
	if err := json.Unmarshal(params, &req); err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}
	tunnel, err := a.cloudflared.Create(ctx, req)
	if err != nil {
		return nil, err
	}
	return tunnel, nil
}

func (a *Agent) handleCloudflaredTunnelRoute(ctx context.Context, params json.RawMessage) (interface{}, error) {
	var req cloudflared.RouteRequest
	if err := json.Unmarshal(params, &req); err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}
	if err := a.cloudflared.Route(ctx, req); err != nil {
		return nil, err
	}
	return map[string]bool{"success": true}, nil
}

func (a *Agent) handleCloudflaredTunnelDelete(ctx context.Context, params json.RawMessage) (interface{}, error) {
	var p struct {
		Ref string `json:"ref"`
	}
	if err := json.Unmarshal(params, &p); err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}
	if err := a.cloudflared.Delete(ctx, p.Ref); err != nil {
		return nil, err
	}
	return map[string]bool{"success": true}, nil
}
