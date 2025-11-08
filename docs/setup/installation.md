# System Installation

Follow these steps to get the AssistantMD running with Docker.

## Prerequisites
*   **Docker Engine or Docker Desktop**
*   **LLM API Key**

## Step-by-Step Setup

### 1. Create a deployment folder and grab the compose file
If you're using the published GHCR image you do **not** need the full source
tree. Create a folder for your deployment and copy the contents of
`docker-compose.yml.example` into `docker-compose.yml`. You can copy/paste from
the docs or download it directly once the public repo is live.

```bash
mkdir assistantmd
cd assistantmd
# paste the compose contents into docker-compose.yml
```

> Clone the repo only when you plan to build a custom image (for example, to
> bake in a different UID/GID or modify the application code). For all other
> cases running the published container is sufficient.

### 2. (Optional) Copy the template if you cloned the repo
If you cloned the repository for local development, duplicate the provided
template:
```bash
cp docker-compose.yml.example docker-compose.yml
```
Skip this step when you manually pasted the compose file in step 1.

### 3. Configure Docker Compose
Open `docker-compose.yml` and update the fields that matter:

- Replace `/absolute/path/to/your/vaults` with the directory that holds your
  vault folders. The container path must stay `/app/data`.
- Keep `./system:/app/system` mounted so settings, logs, and generated secrets
  survive restarts. Create the `system` directory locally if it does not exist:
  `mkdir -p system`.
- Set `TZ` to your local
  [timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) so
  cron-style schedules align with your locale.
- Leave `image: ghcr.io/dodgybadger/assistantmd:latest` as the default. To pin a
  specific release, edit that line and replace `latest` with a tag such as
  `v0.0.0-ci-check`.
- (Optional) Change the host side (the left side) of `127.0.0.1:8000:8000` if
  you need to expose the UI on a different IP/port pair (e.g.
  `192.168.0.1:1234:8000`).

Example vault layout:
```
/Users/yourname/MyVaults/
├── Personal/
├── Work/
└── Research/
```

#### Optional: Customize the runtime user, build locally, or mount the repo
The published GHCR image runs as UID/GID 1000. If your UID/GID is different, you
need to tweak build arguments, or you want to bind mount the repository
(`.:/app`) for local development, copy the override file and edit:

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

Adjust the `build.args`, `user`, and `volumes` entries as needed. When using the
override file, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --build
```

Keep the repository bind mount **out of** production configuration so container
deployments remain reproducible.


### 4. Start the System
```bash
docker compose pull
docker compose up -d
```

This pulls the pinned GHCR image (default: `latest`) and starts the stack. If
you are using the override file to build locally, run the combined command shown
above instead.

This command will:
- Build the Docker image (when needed)
- Start the AssistantMD service
- Begin monitoring your vault directories
- Start the API server on `http://localhost:8000`
- Enable rich console instrumentation for debugging (always available)

Once the container is running, open the **Configuration → Secrets** tab and add the API keys or other credentials you want the system to use. Changes apply immediately—no container restart required.

### 6. Verify Installation
Use the REST API directly to confirm the service is healthy:
```bash
curl http://localhost:8000/api/status
```

You should receive JSON containing overall system status, vault counts, and scheduler information. For additional troubleshooting, tail the container logs:
```bash
docker compose logs -f
```

### 7. Access the Web Interface
The AssistantMD includes a web-based interface for interactive chat and system monitoring.

By default, the interface is available at `http://localhost:8000/` (or whichever host IP/port you configured in the compose file).

**Chat Tab**: Interactive chat with your vaults
**Dashboard Tab**: View system status and execute assistants manually
**Configuration Tab**: Manage models, settings and secrets.

## Vault Organization Patterns

Understanding how to organize your files depends on your specific use case. Here are the two recommended patterns:

### Pattern 1: Single Vault Setup (Simplest)
**When to use**: You have one collection of markdown files you want to work with.

**File structure on your computer**:
```
/home/user/MyNotes/
├── projects/
├── daily-notes/
└── goals.md
```

**Docker volume mapping**: edit the compose volume line to `/home/user/MyNotes:/app/data`.

**Assistant configuration**:
Create assistant files in the root directory:
```
/home/user/MyNotes/
├── assistants/
│   ├── my_assistant.md     # Direct assistant file
│   ├── planning/           # Optional: organize in subfolders
│   │   └── weekly.md
│   └── _chat-sessions/     # System folders (underscore prefix = ignored)
├── projects/
├── daily-notes/
└── goals.md
```

### Pattern 2: Multiple Vaults in Organized Folder (Recommended)
**When to use**: You have separate collections (personal, work, projects) that you want different assistants to handle.

**File structure on your computer**:
```
/home/user/AllMyVaults/
├── Personal/
│   ├── journal/
│   └── goals.md
├── Work/
│   ├── projects/
│   └── meetings/
└── Research/
    ├── papers/
    └── notes/
```

**Docker volume mapping**: edit the compose volume line to `/home/user/AllMyVaults:/app/data`.

**Assistant configuration**:
Create assistant files in each vault's directory:
```
/home/user/AllMyVaults/
├── Personal/
│   ├── assistants/
│   │   ├── personal_planner.md  # Personal assistant config
│   │   └── planning/            # Optional subfolders for organization
│   │       └── weekly.md
│   ├── journal/
│   └── goals.md
├── Work/
│   ├── assistants/
│   │   ├── work_planner.md      # Work assistant config
│   │   └── reports/
│   │       └── monthly.md
│   ├── projects/
│   └── meetings/
└── Research/
    ├── assistants/
    │   ├── research_assistant.md # Research assistant config
    │   └── _chat-sessions/       # System folders (ignored)
    ├── papers/
    └── notes/
```

## Key Principles

1. **The system always starts looking from `/app/data` inside the container**
2. **Each directory under `/app/data` is automatically discovered as a vault**
3. **Each assistant works within exactly one vault and cannot access files from other vaults**
4. **Assistants are defined by markdown files in each vault's `assistants/` directory**
5. **Assistants can be organized in subfolders (one level deep) within `assistants/` for better organization**
6. **Folders prefixed with underscore (e.g., `_chat-sessions`) are automatically ignored**
7. **Each vault will automatically get an `assistants/` subdirectory created for assistant configurations**

## Vault Ignore

If you have directories that should not be treated as vaults, create a `.vaultignore` file in the directory and it will be ignored.

```bash
# Example: Exclude a temporary directory
echo "# Temporary files - not a vault" > /path/to/data/temp/.vaultignore
```
