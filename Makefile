.PHONY: init run-backend run-frontend dev install-backend install-frontend

# Определяем операционную систему для кроссплатформенности venv
ifeq ($(OS),Windows_NT)
	VENV_BIN = backend/.venv/Scripts
else
	VENV_BIN = backend/.venv/bin
endif

# 1. Запуск всего проекта в режиме разработки (параллельно)
dev:
	@echo "🚀 Запуск бэкенда и фронтенда..."
	@make -j 2 run-backend run-frontend

# Запуск только бэкенда
run-backend:
	@echo "🐍 Запуск Python бэкенда..."
	@$(VENV_BIN)/uvicorn main:app --reload --app-dir backend

# Запуск только фронтенда
run-frontend:
	@echo "🅰️ Запуск Angular фронтенда..."
	@cd frontend && npm start

# 2. Быстрая установка всех зависимостей одной командой
init: install-backend install-frontend
	@echo "✅ Все зависимости успешно установлены!"

install-backend:
	@echo "📦 Установка Python зависимостей..."
	@python3 -m venv backend/.venv
	@$(VENV_BIN)/pip install -r backend/requirements.txt

install-frontend:
	@echo "📦 Установка Angular зависимостей..."
	@cd frontend && npm install
