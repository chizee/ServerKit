package connstring

import (
	"encoding/base64"
	"errors"
	"strings"
	"testing"
)

// helper: encode the panel's payload format so the test stays readable
// even as we tweak fields. Mirrors backend/app/services/connection_string.py
// — keep the two in sync.
func encode(payload string) string {
	return Prefix + base64.RawURLEncoding.EncodeToString([]byte(payload))
}

func TestDecode_Roundtrip(t *testing.T) {
	s := encode(`{"url":"https://panel.example.com","token":"sk_reg_abc","expires_at":"2026-05-08T17:00:00Z"}`)
	got, err := Decode(s)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got.URL != "https://panel.example.com" {
		t.Errorf("url = %q", got.URL)
	}
	if got.Token != "sk_reg_abc" {
		t.Errorf("token = %q", got.Token)
	}
	if got.ExpiresAtRaw != "2026-05-08T17:00:00Z" {
		t.Errorf("expires_at_raw = %q", got.ExpiresAtRaw)
	}
	if got.ExpiresAt.IsZero() {
		t.Errorf("expires_at not parsed: %v", got.ExpiresAt)
	}
}

func TestDecode_TrimsWhitespace(t *testing.T) {
	s := encode(`{"url":"https://x","token":"t"}`)
	// Clipboard pastes often have a trailing newline; verify Decode
	// doesn't reject a string just because of that.
	if _, err := Decode("\n  " + s + "  \n"); err != nil {
		t.Fatalf("decode with whitespace: %v", err)
	}
}

func TestDecode_RejectsUnknownVersion(t *testing.T) {
	_, err := Decode("sk_conn_v9.aaaa")
	if !errors.Is(err, ErrUnknownVersion) {
		t.Errorf("want ErrUnknownVersion, got %v", err)
	}

	_, err = Decode("not-a-connection-string")
	if !errors.Is(err, ErrUnknownVersion) {
		t.Errorf("want ErrUnknownVersion for missing prefix, got %v", err)
	}
}

func TestDecode_RejectsEmpty(t *testing.T) {
	if _, err := Decode(""); err == nil {
		t.Errorf("want error for empty input")
	}
	if _, err := Decode("   "); err == nil {
		t.Errorf("want error for whitespace-only input")
	}
}

func TestDecode_RejectsMissingFields(t *testing.T) {
	cases := []string{
		`{"token":"t"}`,
		`{"url":"https://x"}`,
		`{}`,
	}
	for _, payload := range cases {
		_, err := Decode(encode(payload))
		if err == nil {
			t.Errorf("expected error for payload %q", payload)
			continue
		}
		if !strings.Contains(err.Error(), "missing url or token") {
			t.Errorf("payload %q: unexpected error %v", payload, err)
		}
	}
}

func TestDecode_RejectsCorruptBase64(t *testing.T) {
	// Garbage after the prefix isn't valid base64 in either alphabet.
	_, err := Decode(Prefix + "!!!not-base64!!!")
	if err == nil {
		t.Errorf("want error for corrupt base64")
	}
}

func TestDecode_AcceptsPaddedBase64(t *testing.T) {
	// Some clipboards (notably pasting through certain terminals) round-
	// trip the URL-safe alphabet through a padded form. Decode tolerates
	// either, so a hand-edited string still works.
	payload := []byte(`{"url":"https://x","token":"t"}`)
	padded := Prefix + base64.URLEncoding.EncodeToString(payload)
	if _, err := Decode(padded); err != nil {
		t.Errorf("padded decode: %v", err)
	}
}
