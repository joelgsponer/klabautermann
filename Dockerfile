# ── Builder stage ──────────────────────────────────────────────
FROM rust:bookworm AS builder

WORKDIR /build
COPY .git/ .git/
COPY Cargo.toml Cargo.lock ./
COPY build.rs ./
COPY src/ src/
COPY migrations/ migrations/
COPY templates/ templates/

RUN cargo build --release

# ── Runtime stage ─────────────────────────────────────────────
FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates libsqlite3-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /build/target/release/klabautermann /app/klabautermann
COPY migrations/ /app/migrations/
COPY templates/ /app/templates/
COPY static/ /app/static/

RUN mkdir -p /app/data /app/media

ENV LISTEN_ADDR=0.0.0.0:3000
EXPOSE 3000

CMD ["/app/klabautermann"]
