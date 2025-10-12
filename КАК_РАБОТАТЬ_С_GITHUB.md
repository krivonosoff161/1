# 🚀 Работа с проектом через GitHub

## ✅ Проект успешно загружен!

Ваш проект теперь доступен на GitHub: **https://github.com/krivonosoff161/1**

---

## 📥 Клонирование проекта на новое устройство

### Шаг 1: Установка Git

Если Git еще не установлен:
- **Windows**: https://git-scm.com/download/win
- **Linux**: `sudo apt install git`
- **Mac**: `brew install git`

### Шаг 2: Клонирование репозитория

```bash
# Клонируем проект
git clone https://github.com/krivonosoff161/1.git

# Переходим в папку проекта
cd 1
```

### Шаг 3: Установка зависимостей

```bash
# Создаем виртуальное окружение
python -m venv venv

# Активируем виртуальное окружение
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Устанавливаем зависимости
pip install -r requirements.txt
```

### Шаг 4: Настройка переменных окружения

```bash
# Копируем пример файла .env
cp env.example .env

# Редактируем .env и вставляем ваши API ключи OKX
notepad .env  # Windows
nano .env     # Linux/Mac
```

### Шаг 5: Запуск бота

```bash
# Windows:
start_bot.bat

# Linux/Mac:
python run_bot.py
```

---

## 🔄 Синхронизация изменений

### Когда вы работаете на текущем устройстве

После внесения изменений:

```bash
# 1. Добавляем все изменения
git add .

# 2. Создаем commit с описанием изменений
git commit -m "Описание ваших изменений"

# 3. Загружаем на GitHub
git push origin master
```

### Когда работаете на другом устройстве

Перед началом работы:

```bash
# Получаем последние изменения с GitHub
git pull origin master
```

---

## 📝 Полезные Git команды

```bash
# Посмотреть статус (какие файлы изменены)
git status

# Посмотреть историю коммитов
git log --oneline

# Отменить локальные изменения в файле
git checkout -- имя_файла

# Посмотреть что изменилось в файлах
git diff

# Создать новую ветку для экспериментов
git checkout -b new-feature

# Вернуться на master
git checkout master
```

---

## 🔥 Типичный рабочий процесс

### На компьютере А:
```bash
# Работаем, вносим изменения...
git add .
git commit -m "Добавил новую стратегию"
git push origin master
```

### На компьютере Б:
```bash
# Получаем изменения с компьютера А
git pull origin master

# Работаем, вносим изменения...
git add .
git commit -m "Исправил баг в логике"
git push origin master
```

### Снова на компьютере А:
```bash
# Получаем изменения с компьютера Б
git pull origin master

# Продолжаем работу...
```

---

## ⚠️ Важные замечания

### 1. Файл `.env` не загружается на GitHub
Это сделано специально для безопасности - **ваши API ключи не попадут в публичный репозиторий**.

На каждом новом устройстве:
1. Скопируйте `env.example` в `.env`
2. Впишите ваши настоящие API ключи

### 2. Логи и база данных не синхронизируются
Файлы `*.log` и `trading_bot.db` добавлены в `.gitignore` - они остаются локальными на каждом устройстве.

### 3. Виртуальное окружение `venv/` не синхронизируется
На каждом устройстве нужно создать свое виртуальное окружение:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

---

## 🆘 Решение проблем

### Конфликты при git pull

Если при `git pull` возникают конфликты:

```bash
# Вариант 1: Сохранить свою локальную версию
git checkout --ours имя_файла
git add .
git commit -m "Resolved conflicts"

# Вариант 2: Взять версию с GitHub
git checkout --theirs имя_файла
git add .
git commit -m "Resolved conflicts"

# Вариант 3: Отменить все локальные изменения и взять с GitHub
git reset --hard origin/master
```

### Забыли сделать commit перед pull

```bash
# Сохраните изменения во временное хранилище
git stash

# Получите изменения с GitHub
git pull origin master

# Восстановите ваши изменения
git stash pop
```

---

## 🎯 Рекомендации

1. **Делайте commit часто** - маленькие коммиты легче отслеживать
2. **Пишите понятные сообщения** - `"fix bug"` ❌, `"Fixed _can_trade() indentation error"` ✅
3. **Pull перед началом работы** - избежите конфликтов
4. **Push в конце рабочего дня** - изменения будут доступны везде
5. **Используйте ветки для экспериментов** - master остается стабильным

---

## 📚 Дополнительные ресурсы

- **Git шпаргалка**: https://education.github.com/git-cheat-sheet-education.pdf
- **Git для новичков**: https://git-scm.com/book/ru/v2
- **GitHub Desktop** (графический интерфейс): https://desktop.github.com/

---

**Ваш репозиторий**: https://github.com/krivonosoff161/1

Теперь вы можете работать с проектом с любого устройства! 🚀

