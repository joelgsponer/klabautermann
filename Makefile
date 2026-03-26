.PHONY: dev build run clean

dev:
	RUST_LOG=klabautermann=debug,tower_http=debug cargo run

build:
	cargo build --release

run: build
	./target/release/klabautermann

clean:
	cargo clean
	rm -f klabautermann.db klabautermann.db-wal klabautermann.db-shm
