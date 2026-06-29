package hannah

import (
	"testing"
	"time"
)

func TestDispatch_DifferentDevicesRunConcurrently(t *testing.T) {
	releaseA := make(chan struct{})
	bDone := make(chan struct{}, 1)

	d := newPlayAudioDispatcher(func(deviceID string, pcm []byte, sampleRate int32, isLast bool) {
		switch deviceID {
		case "a":
			<-releaseA // blocks until the test releases it, simulating a long SendTTSChunk
		case "b":
			bDone <- struct{}{}
		}
	})
	defer func() {
		close(releaseA)
		d.stop()
	}()

	d.dispatch("a", []byte("chunk"), 24000, false)

	select {
	case <-bDone:
		t.Fatal("device b callback ran before being dispatched")
	case <-time.After(20 * time.Millisecond):
	}

	d.dispatch("b", []byte("chunk"), 24000, false)

	select {
	case <-bDone:
	case <-time.After(time.Second):
		t.Fatal("device b was not served while device a was still blocked — devices are not running concurrently")
	}
}

func TestDispatch_PreservesOrderPerDevice(t *testing.T) {
	const n = 50
	got := make(chan byte, n)

	d := newPlayAudioDispatcher(func(deviceID string, pcm []byte, sampleRate int32, isLast bool) {
		got <- pcm[0]
	})
	defer d.stop()

	for i := 0; i < n; i++ {
		d.dispatch("device", []byte{byte(i)}, 24000, false)
	}

	for i := 0; i < n; i++ {
		select {
		case b := <-got:
			if b != byte(i) {
				t.Fatalf("chunk %d arrived out of order: got %d", i, b)
			}
		case <-time.After(time.Second):
			t.Fatalf("timed out waiting for chunk %d", i)
		}
	}
}

func TestDispatch_IsLastPropagated(t *testing.T) {
	results := make(chan bool, 2)
	d := newPlayAudioDispatcher(func(deviceID string, pcm []byte, sampleRate int32, isLast bool) {
		results <- isLast
	})
	defer d.stop()

	d.dispatch("device", []byte("chunk"), 24000, false)
	d.dispatch("device", []byte("chunk"), 24000, true)

	for _, want := range []bool{false, true} {
		select {
		case got := <-results:
			if got != want {
				t.Fatalf("isLast = %v, want %v", got, want)
			}
		case <-time.After(time.Second):
			t.Fatal("timed out waiting for callback")
		}
	}
}

func TestStop_DrainsAndReturns(t *testing.T) {
	const n = 10
	processed := make(chan struct{}, n)

	d := newPlayAudioDispatcher(func(deviceID string, pcm []byte, sampleRate int32, isLast bool) {
		processed <- struct{}{}
	})

	for i := 0; i < n; i++ {
		d.dispatch("device", []byte{byte(i)}, 24000, false)
	}

	d.stop() // must not return before all already-queued jobs have run

	if len(processed) != n {
		t.Fatalf("processed %d jobs, want %d — stop() returned before draining the queue", len(processed), n)
	}
}
