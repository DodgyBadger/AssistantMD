## Upgrading

⚠️ Beta software. Always check the [release notes](https://github.com/DodgyBadger/AssistantMD/releases/latest) for breaking changes.  
⚠️ Back up your notes and the `AssistantMD/system` folder.

***If you are using the default docker image:***
```
docker compose down
docker compose pull
docker compose up -d
```

***If you cloned the repo and built a custom image:***
```
docker compose down
git pull
docker compuse up -d --build
```