package hannah

import "sync"

// queueCapacity bounds each device's pending-chunk queue. PlayAudioCommand
// chunks are ~100ms of audio each (see core/hannah/grpc_server.py
// stream_audio_to_proxy), so 512 slots cover ~51s of queued announcement
// audio per device — far beyond any realistic announcement length.
const queueCapacity = 512

// playAudioJob is one PlayAudioCommand chunk queued for a specific device.
type playAudioJob struct {
	pcm        []byte
	sampleRate int32
	isLast     bool
}

// playAudioDispatcher fans incoming PlayAudioCommand chunks out to one
// worker goroutine per device, so a slow/blocking satellite (UDP pacing
// sleep in udp.Server.SendTTSChunk) cannot delay chunks destined for other
// satellites. Order is preserved per device (FIFO); different devices are
// served concurrently.
type playAudioDispatcher struct {
	onPlayAudio PlayAudioFunc

	mu     sync.Mutex
	queues map[string]chan playAudioJob
	wg     sync.WaitGroup
}

func newPlayAudioDispatcher(onPlayAudio PlayAudioFunc) *playAudioDispatcher {
	return &playAudioDispatcher{
		onPlayAudio: onPlayAudio,
		queues:      make(map[string]chan playAudioJob),
	}
}

// dispatch enqueues a chunk for deviceID, starting its worker goroutine
// lazily on first use. The channel send happens without holding d.mu, so a
// full queue for one device only blocks chunks for that device — it never
// stalls dispatch for other devices.
func (d *playAudioDispatcher) dispatch(deviceID string, pcm []byte, sampleRate int32, isLast bool) {
	ch := d.workerChan(deviceID)
	ch <- playAudioJob{pcm: pcm, sampleRate: sampleRate, isLast: isLast}
}

func (d *playAudioDispatcher) workerChan(deviceID string) chan playAudioJob {
	d.mu.Lock()
	defer d.mu.Unlock()
	ch, ok := d.queues[deviceID]
	if !ok {
		ch = make(chan playAudioJob, queueCapacity)
		d.queues[deviceID] = ch
		d.wg.Add(1)
		go d.runWorker(deviceID, ch)
	}
	return ch
}

func (d *playAudioDispatcher) runWorker(deviceID string, ch chan playAudioJob) {
	defer d.wg.Done()
	for job := range ch {
		d.onPlayAudio(deviceID, job.pcm, job.sampleRate, job.isLast)
	}
}

// stop closes all device queues and waits for their workers to drain
// already-queued jobs and exit. Must be called when the owning stream ends
// (lost connection or ctx cancellation) to avoid leaking worker goroutines
// across reconnects.
func (d *playAudioDispatcher) stop() {
	d.mu.Lock()
	for _, ch := range d.queues {
		close(ch)
	}
	d.queues = make(map[string]chan playAudioJob)
	d.mu.Unlock()
	d.wg.Wait()
}
