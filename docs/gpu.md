# GPU acceleration

Synsci Delphi runs its embedding model (sentence-transformers) inside a Docker container. Whether that container can use a GPU depends on your platform.

## Platform matrix

| Platform | GPU usable in Docker? | What happens |
|---|---|---|
| **Linux + NVIDIA + nvidia-container-toolkit** | ✅ | `delphi init` detects the GPU and asks CPU vs CUDA. |
| **Linux + NVIDIA + no toolkit** | ❌ | Init detects the GPU, prints the install command for your distro, falls back to CPU. Run the command, re-init to enable GPU. |
| **Linux without NVIDIA GPU** | ❌ | Silent CPU. No prompt. |
| **macOS (Apple Silicon or Intel)** | ❌ | Docker Desktop on Mac can't pass GPU to Linux containers — full stop. The CLI flags this once during install and runs CPU-only. See **Native MPS workaround** below if you really need acceleration. |
| **Windows + WSL2 + NVIDIA + WSL toolkit** | ✅ | Treated as Linux. Probe + prompt the same way. |
| **Windows native (no WSL2)** | ❌ | Same limitation as macOS — no GPU passthrough. CPU only. |

## What we probe

`delphi init` runs three checks and acts on the first failure:

1. **Platform** — short-circuit on macOS.
2. **`nvidia-smi -L`** — host has a working NVIDIA driver + at least one GPU.
3. **`docker info --format '{{.Runtimes}}'`** — Docker daemon has the `nvidia` runtime registered (i.e. nvidia-container-toolkit is installed and the daemon was restarted).

If all three pass, you get the CPU/CUDA picker. If (2) passes but (3) doesn't, you get a distro-specific install hint and a CPU fallback.

## Distro install commands

When the toolkit is missing, `delphi init` prints one of these. You don't need to memorize them — they'll show in your terminal at install time.

```bash
# Arch / Manjaro
yay -S nvidia-container-toolkit && sudo systemctl restart docker

# Ubuntu / Debian
sudo apt install -y nvidia-container-toolkit && sudo systemctl restart docker

# Fedora / RHEL / Rocky / Alma
sudo dnf install -y nvidia-container-toolkit && sudo systemctl restart docker
```

Then verify:

```bash
docker info --format '{{.Runtimes}}'   # expect `nvidia` in the list
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

## What changes when GPU is enabled

- `state.json` records `useGpu: true`. Every subsequent `delphi start / open / reload / status / logs / stop` re-applies the GPU reservation.
- The api and worker containers each get `deploy.resources.reservations.devices` for `nvidia` — both need it because each holds its own SentenceTransformer instance and CUDA contexts don't share across processes.
- `EMBEDDING_DEVICE=cuda` is written to `.env` so sentence-transformers explicitly targets the GPU instead of relying on its `auto` heuristic.

## Switching CPU ↔ GPU after install

```bash
delphi config
```

Pick Local provider again, then choose CPU or CUDA at the device prompt. The transactional config flow re-applies the override file and validates with an end-to-end embed probe before committing.

## Native MPS workaround (macOS)

If you're on Apple Silicon and really want MPS acceleration, the api needs to run *outside* Docker. The dashboard and postgres can stay containerized. **This isn't an officially supported install path yet — you're piecing it together by hand.**

Rough recipe:

```bash
# 1. Start postgres + frontend in docker (skip api/worker)
cd ~/.synsci/delphi/source
docker compose up -d postgres frontend

# 2. Run the api natively in a uv-managed venv pointing at the dockerized DB
cd backend
uv sync
EMBEDDING_PROVIDER=local \
EMBEDDING_DEVICE=mps \
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5 \
DATABASE_URL=postgresql://synsc:<password-from-env>@localhost:5432/synsc \
SYSTEM_PASSWORD=<password-from-env> \
SERVER_SECRET=<from-env> \
uv run synsc-context serve http
```

Caveats:
- You're responsible for keeping `.env` values in sync between the dockerized postgres and the host-run api.
- `delphi reload` won't restart your host-run api; you stop/start it manually.
- The MCP proxy still works because it just talks to `localhost:8742`.

A first-class native-mode install path is on the roadmap; the CLI currently doesn't manage host processes.

## Why not just use Apple Silicon GPU through Docker?

Docker Desktop on macOS runs containers in a hypervisor-managed Linux VM. The VM has no MPS / Metal driver — those are macOS-host-only Apple frameworks. There's no `--gpus all` equivalent for Mac. NVIDIA pass-through to Linux containers is the only widely-supported GPU-in-Docker story.

This isn't a Delphi limitation; it's a Docker-on-Mac limitation. Docker, Inc. has discussed it but no implementation has shipped.
