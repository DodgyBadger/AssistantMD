## Prerequisites
*   [Docker Engine](https://docs.docker.com/engine/install/) or [Docker Desktop](https://www.docker.com/products/docker-desktop/)
*   At least one LLM API Key

### Create a folder for your deployment, structured as follows:
```
assistantmd
├── system/
└── docker-compose.yml
```
_Pre-creating the `system` folder is important to avoid a "permission denied" error. See the section on file permission and customizing the runtime user below._

Copy the contents of
`docker-compose.yml.example` into `docker-compose.yml`.

```bash
mkdir AssistantMD
cd AssistantMD
mkdir system
nano docker-compose.yml
```
### Open `docker-compose.yml` and update the following:

- Replace `/absolute/path/to/your/vaults` with the directory that holds your
  vault folders. See examples below.
- If you have directories in that path that should not be treated as vaults, create a `.vaultignore` file in the directory and it will be ignored.
- **Do not** change the right hand side: `/app/data` or the `./system:/app/system` mount.
- Set `TZ` to your local [timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) so
  that scheduled workflows run when you expect them to.

**Optional**
- Change the host side (the left side) of `127.0.0.1:8000:8000` if
  you need to expose the UI on a different IP/port (e.g. `192.168.0.1:1234:8000`).
- Change the `latest` tag in `image: ghcr.io/dodgybadger/assistantmd:latest` to lock a
  specific release. See the [repository](https://github.com/DodgyBadger/AssistantMD/tags) for all tags.


### Start the System
`docker compose up -d`

**Verify Installation**
`docker ps` should show assistantMD running. If you see "restarting", something is wrong. Run `docker logs assistantMD` to check for startup errors.

Access the web interface at `http://localhost:8000/` (or whichever host IP/port you configured in the compose file).

**Chat Tab**: Interactive chat with your vaults
**Workflow Tab**: View all workflows and execute workflows manually
**Configuration Tab**: Manage models, settings and secrets.

Open the **Configuration** tab and add at least one LLM API key under **Secrets**. Changes apply immediately—no container restart required.


## Optional Setup

## Integrations

**Web search**: The default web search tool uses the free duckduckgo library. This is enabled by default. To enable more advanced searches, web extraction and web crawling, you can add a [Tavily API key](https://www.tavily.com). The free tier will be sufficient for many users and is worth grabbing.

**Code execution**: To enable the code execution tool, add a [LibreChat API key](https://code.librechat.ai). This is a paid service only. After testing several options, I settled on LibreChat Code Intepretter because of security, low latency and the wide set of languages it supports. I will consider other options as they come to my attention.

**Logfire**: AssistantMD uses the logfire library for rich console logging (what you see if you run `docker logs assistantmd`). You can add a [Logfire API key](https://pydantic.dev) to get even more data including full details of every LLM call. The free tier will be sufficient for many users and is worth grabbing. Be sure to also set logfire=true in the Configuration tab of the web interface.


### File permission and customizing the runtime user
The default docker image runs as UID 1000 inside the container. This is the most common non-root user ID on linux and Mac systems and will work in most cases. It ensures that markdown files edited or written by the app remain accessible to you on the host. If it ran as root inside the container, you would lose access to any markdown files it touched. This works in reverse also. If the volumes being mounted into the container (`/absolute/path/to/your/vaults` and `./system`) are created by root on the host (i.e. you let docker create them or use `sudo`), then UID 1000 inside the container will not have access.

If you get "permission denied" when loading the app, first make sure that your user on the host is UID 1000 by running `id` at a command line. Then make sure that the two mounted folders are not owned by root. 

If your UID is not 1000, then you need to build a custom image. There are also scenarios where you might want to run as root inside the container, such as hosting AssistantMD and syncing your markdown files to a remote server.

Clone the repo:
`git clone https://github.com/DodgyBadger/AssistantMD.git`

Rename both docker compose files

```bash
cd AssistantMD
cp docker-compose.yml.example docker-compose.yml
cp docker-compose.override.yml.example docker-compose.override.yml
```

Edit docker-compose.yml as above.
In docker-compose.override.yml, edit `build.args` and `user` as needed. E.g.

```
    args:
      USER_ID: 1001
      GROUP_ID: 1001
  user: "1001:1001"
```

Build and run the image: `docker compose up -d --build`


## Vault Path Examples

**Single Vault**

File structure on your computer:
```
/home/user/MyNotes/
├── projects/
├── daily-notes/
└── goals.md
```
Docker compose volume mount reads: `/home/user/MyNotes:/app/data`.

**Multiple Vaults**

File structure on your computer:
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

Docker compose volume mount reads: `/home/user/AllMyVaults:/app/data`.

