package udp

import (
	"encoding/json"
	"net"
	"testing"
	"time"
)

// makeServer creates a Server without binding a port.
// Callbacks can be registered before calling Start().
func makeServer() *Server {
	return NewServer("127.0.0.1:0")
}

// makeAddr builds a UDPAddr from an IP string and port.
func makeAddr(ip string, port int) *net.UDPAddr {
	return &net.UDPAddr{IP: net.ParseIP(ip), Port: port}
}

// controlPayload encodes a control message as JSON bytes.
func controlPayload(t *testing.T, msg map[string]any) []byte {
	t.Helper()
	b, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
	}
	return b
}

// --- handleControl: register ------------------------------------------------

func TestRegister_AddsSatellite(t *testing.T) {
	s := makeServer()
	addr := makeAddr("192.168.1.100", 7776)

	s.handleControl(controlPayload(t, map[string]any{
		"type":   "register",
		"device": "wohnzimmer-esp",
	}), addr)

	s.mu.Lock()
	_, ok := s.satellites["wohnzimmer-esp"]
	s.mu.Unlock()

	if !ok {
		t.Fatal("satellite was not registered")
	}
}

func TestRegister_CallsCallback(t *testing.T) {
	s := makeServer()

	done := make(chan struct{}, 1)
	s.OnSatelliteChange(func(device, address, seed string, registered bool) {
		if device == "wohnzimmer-esp" && registered {
			done <- struct{}{}
		}
	})

	s.handleControl(controlPayload(t, map[string]any{
		"type":   "register",
		"device": "wohnzimmer-esp",
	}), makeAddr("192.168.1.100", 7776))

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("onSatelliteChange was not called")
	}
}

func TestRegister_SetsLastHeartbeat(t *testing.T) {
	s := makeServer()
	before := time.Now()

	s.handleControl(controlPayload(t, map[string]any{
		"type":   "register",
		"device": "wohnzimmer-esp",
	}), makeAddr("192.168.1.100", 7776))

	s.mu.Lock()
	ts := s.satellites["wohnzimmer-esp"].lastHeartbeat
	s.mu.Unlock()

	if ts.Before(before) {
		t.Error("lastHeartbeat was not set on registration")
	}
}

// --- handleControl: heartbeat -----------------------------------------------

func TestHeartbeat_UpdatesTimestamp(t *testing.T) {
	s := makeServer()
	addr := makeAddr("192.168.1.100", 7776)
	old := time.Now().Add(-10 * time.Second)

	s.mu.Lock()
	s.satellites["wohnzimmer-esp"] = &satellite{
		audioAddr: addr, ttsAddr: addr,
		lastHeartbeat: old,
	}
	s.mu.Unlock()

	s.handleControl(controlPayload(t, map[string]any{
		"type":   "heartbeat",
		"device": "wohnzimmer-esp",
	}), addr)

	s.mu.Lock()
	newTs := s.satellites["wohnzimmer-esp"].lastHeartbeat
	s.mu.Unlock()

	if !newTs.After(old) {
		t.Error("lastHeartbeat was not updated by heartbeat")
	}
}

// --- checkTimeouts ----------------------------------------------------------

func TestCheckTimeouts_RemovesStale(t *testing.T) {
	s := makeServer()
	addr := makeAddr("192.168.1.100", 7776)

	s.mu.Lock()
	s.satellites["stale-sat"] = &satellite{
		audioAddr: addr, ttsAddr: addr,
		lastHeartbeat: time.Now().Add(-31 * time.Second),
	}
	s.mu.Unlock()

	s.checkTimeouts()

	s.mu.Lock()
	_, exists := s.satellites["stale-sat"]
	s.mu.Unlock()

	if exists {
		t.Error("stale satellite should have been removed")
	}
}

func TestCheckTimeouts_CallsCallbackWithFalse(t *testing.T) {
	s := makeServer()
	addr := makeAddr("192.168.1.100", 7776)

	done := make(chan bool, 1)
	s.OnSatelliteChange(func(device, address, seed string, registered bool) {
		done <- registered
	})

	s.mu.Lock()
	s.satellites["stale-sat"] = &satellite{
		audioAddr: addr, ttsAddr: addr,
		lastHeartbeat: time.Now().Add(-31 * time.Second),
	}
	s.mu.Unlock()

	s.checkTimeouts()

	select {
	case registered := <-done:
		if registered {
			t.Error("callback should signal offline (registered=false)")
		}
	case <-time.After(time.Second):
		t.Fatal("onSatelliteChange was not called")
	}
}

func TestCheckTimeouts_FreshNotRemoved(t *testing.T) {
	s := makeServer()
	addr := makeAddr("192.168.1.100", 7776)

	s.mu.Lock()
	s.satellites["fresh-sat"] = &satellite{
		audioAddr: addr, ttsAddr: addr,
		lastHeartbeat: time.Now(),
	}
	s.mu.Unlock()

	s.checkTimeouts()

	s.mu.Lock()
	_, exists := s.satellites["fresh-sat"]
	s.mu.Unlock()

	if !exists {
		t.Error("fresh satellite should not have been removed")
	}
}

func TestCheckTimeouts_PartialTimeout(t *testing.T) {
	s := makeServer()
	addr := makeAddr("192.168.1.100", 7776)

	s.mu.Lock()
	s.satellites["stale-sat"] = &satellite{
		audioAddr: addr, ttsAddr: addr,
		lastHeartbeat: time.Now().Add(-31 * time.Second),
	}
	s.satellites["fresh-sat"] = &satellite{
		audioAddr:     makeAddr("192.168.1.101", 7776),
		ttsAddr:       makeAddr("192.168.1.101", 7776),
		lastHeartbeat: time.Now(),
	}
	s.mu.Unlock()

	s.checkTimeouts()

	s.mu.Lock()
	_, staleExists := s.satellites["stale-sat"]
	_, freshExists := s.satellites["fresh-sat"]
	s.mu.Unlock()

	if staleExists {
		t.Error("stale satellite should have been removed")
	}
	if !freshExists {
		t.Error("fresh satellite should not have been removed")
	}
}

// --- audioSession.pcm -------------------------------------------------------

func TestAudioSession_PCM_ConcatenatesChunks(t *testing.T) {
	sess := &audioSession{
		chunks: [][]byte{
			{0x01, 0x02},
			{0x03, 0x04},
			{0x05},
		},
	}
	got := sess.pcm()
	want := []byte{0x01, 0x02, 0x03, 0x04, 0x05}
	if len(got) != len(want) {
		t.Fatalf("pcm() len = %d, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("pcm()[%d] = 0x%02x, want 0x%02x", i, got[i], want[i])
		}
	}
}

func TestAudioSession_PCM_Empty(t *testing.T) {
	sess := &audioSession{}
	got := sess.pcm()
	if len(got) != 0 {
		t.Errorf("pcm() on empty session = %v, want []", got)
	}
}
