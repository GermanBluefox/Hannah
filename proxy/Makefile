MODULE := dev.kernstock.net/gessinger/voice/hannah/proxy

.PHONY: build run tidy

build:
	go build -o bin/proxy ./cmd/proxy

run:
	go run ./cmd/proxy --config config.yaml

tidy:
	go mod tidy

# Proto stub generation: use ./gen_proto.sh, not a Makefile target (#45 — unifies
# with hannah-timer's proto/gen.sh, the other Go consumer of hannah.proto, which
# has no Makefile at all).
