# Використовуємо легкий образ Python
FROM python:3.11-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Оновлюємо pip до останньої версії
RUN pip install --upgrade pip

# Копіюємо requirements.txt і встановлюємо залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код
COPY . .

# Запускаємо бот
CMD ["python", "trading_bot.py"]