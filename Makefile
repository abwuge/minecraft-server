SHELL := /usr/bin/env bash
COMPOSE := docker compose

.PHONY: help build up down restart logs ps \
        logs-proxy logs-survival logs-creative \
        console-survival console-creative \
        upgrade backup-now clean-volumes

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?##"};{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}'

build:  ## 构建所有镜像
	$(COMPOSE) build

up:     ## 启动整个群组
	$(COMPOSE) up -d

down:   ## 停止并移除容器(保留 volume)
	$(COMPOSE) down

restart: ## 重启所有服务
	$(COMPOSE) restart

ps:     ## 查看容器状态
	$(COMPOSE) ps

logs:           ## 跟随所有日志
	$(COMPOSE) logs -f --tail=200

logs-proxy:     ## proxy 日志
	$(COMPOSE) logs -f --tail=200 proxy
logs-survival:  ## survival 日志
	$(COMPOSE) logs -f --tail=200 survival
logs-creative:  ## creative 日志
	$(COMPOSE) logs -f --tail=200 creative

console-survival: ## RCON 进入 survival 控制台
	@$(COMPOSE) exec -e RCON_PASSWORD survival sh -c \
	  'command -v mcrcon >/dev/null || (apt-get update && apt-get install -y mcrcon >/dev/null); \
	   mcrcon -H 127.0.0.1 -P 25575 -p "$$RCON_PASSWORD" -t'

console-creative:
	@$(COMPOSE) exec -e RCON_PASSWORD creative sh -c \
	  'command -v mcrcon >/dev/null || (apt-get update && apt-get install -y mcrcon >/dev/null); \
	   mcrcon -H 127.0.0.1 -P 25575 -p "$$RCON_PASSWORD" -t'

upgrade: ## 拉取最新镜像并滚动更新 (玩家会被踢)
	$(COMPOSE) pull
	$(COMPOSE) up -d

backup-now: ## TODO: restic 备份 (后续里程碑实现)
	@echo "[TODO] backup not implemented yet"

clean-volumes: ## 危险: 删除所有 volume (世界丢失!)
	@read -p "确认删除所有 volume? 输入 YES: " ans; [ "$$ans" = "YES" ] || exit 1
	$(COMPOSE) down -v
