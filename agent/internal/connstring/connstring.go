// Package connstring decodes the panel's "connection string" — a single
// base64-packed blob the user copies from the ServerKit panel and pastes
// into the agent's pairing wizard. It bundles the panel URL plus a
// single-use registration token, replacing the older flow where the user
// typed those into separate fields.
//
// Format: ``sk_conn_v1.<base64url(json_payload)>``
//
// The version prefix exists so older agents reject newer payloads cleanly
// instead of mis-parsing them. Today's payload is intentionally tiny —
// just the URL, the token, and an optional expiry the agent treats as
// advisory (the panel is the authoritative source of truth on whether the
// token is still good).
package connstring

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

const (
	// Prefix is the version tag that introduces every v1 connection string.
	Prefix = "sk_conn_v1."
)

// Decoded is the payload encoded inside a connection string.
type Decoded struct {
	URL       string    `json:"url"`
	Token     string    `json:"token"`
	ExpiresAt time.Time `json:"-"` // parsed from the raw payload below
	// Raw expiry kept verbatim so we can show the user the panel's exact
	// formatting (or "never") without re-stringifying.
	ExpiresAtRaw string `json:"expires_at,omitempty"`
}

// ErrUnknownVersion is returned when the prefix is missing or names a
// version this build doesn't understand. Callers should surface this as
// "your panel is newer than this agent" rather than a generic decode error
// — it's almost always the cause.
var ErrUnknownVersion = errors.New("connstring: unknown version prefix")

// Decode parses a connection string. Whitespace surrounding the input is
// stripped (paste-from-clipboard often picks up a trailing newline).
func Decode(s string) (*Decoded, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, errors.New("connstring: empty input")
	}
	if !strings.HasPrefix(s, Prefix) {
		return nil, ErrUnknownVersion
	}
	payload := strings.TrimPrefix(s, Prefix)

	// We use the URL-safe alphabet without padding on the panel side; allow
	// either padded or unpadded inputs here so a hand-edited string still
	// decodes.
	raw, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		raw, err = base64.URLEncoding.DecodeString(payload)
	}
	if err != nil {
		return nil, fmt.Errorf("connstring: base64 decode: %w", err)
	}

	// Parse twice — once into the public Decoded struct (gets URL+Token),
	// then into a small auxiliary struct to capture the expiry as both a
	// time.Time and the original string.
	var out Decoded
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, fmt.Errorf("connstring: json decode: %w", err)
	}
	if out.URL == "" || out.Token == "" {
		return nil, errors.New("connstring: payload missing url or token")
	}

	var aux struct {
		ExpiresAt string `json:"expires_at"`
	}
	_ = json.Unmarshal(raw, &aux)
	out.ExpiresAtRaw = aux.ExpiresAt
	if aux.ExpiresAt != "" {
		if t, perr := time.Parse(time.RFC3339, aux.ExpiresAt); perr == nil {
			out.ExpiresAt = t
		}
	}

	return &out, nil
}
