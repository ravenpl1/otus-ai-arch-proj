#!/usr/bin/env python3
"""Скрипт загрузчик данных RFSD из CSV файла через API.

Читает CSV файл датасета RFSD и загружает данные батчами
на backend через POST /ingest-rfsd/batch с авторизацией.

Использование:
    # Получить токен можно через Swagger UI:
    # 1. Открыть http://localhost:8000/docs
    # 2. Нажать "Authorize" и войти как maria / maria123
    # 3. Скопировать access_token из перехваченного запроса

    # Загрузить ВСЕ данные (по умолчанию batch-size=50):
    python scripts/ingest_rfsd.py --token eyJhbGci...

    # Посмотреть структуру батчей при batch-size=100:
    python scripts/ingest_rfsd.py --token T --batch-size 100 --list-batches

    # Загрузить один конкретный батч (например 253):
    python scripts/ingest_rfsd.py --token T --batch-size 100 --batch 253

    # Загрузить диапазон батчей (253–260):
    python scripts/ingest_rfsd.py --token T --batch-size 100 --batch 253-260
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def _clean_value(value: str | None) -> Any:
    """Очищает значение из CSV: пустые/NaN → None, числа → float."""
    if value is None:
        return None
    value = value.strip()
    if not value or value.lower() in ("nan", "none", "null", ""):
        return None
    # Попытка конвертировать в число
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return value


# Поля, которые должны всегда быть строкой (не конвертировать в float)
_STRING_FIELDS = {"inn", "ogrn", "okved", "short_name", "full_name", "okved_section", "region", "creation_date", "dissolution_date"}


def _csv_row_to_record(row: dict) -> dict:
    """Преобразует строку CSV в словарь для API.

    CSV файл использует имена полей с заглавными буквами (B_assets, PL_revenue),
    а API ожидает строчные (b_assets, pl_revenue).
    """
    # Маппинг CSV полей → API полей
    field_map = {
        "inn": "inn",
        "ogrn": "ogrn",
        "short_name": "short_name",
        "full_name": "full_name",
        "okved": "okved",
        "okved_section": "okved_section",
        "region": "region",
        "age": "age",
        "creation_date": "creation_date",
        "dissolution_date": "dissolution_date",
        # Финансовые поля (CSV использует заглавные)
        "B_assets": "b_assets",
        "b_assets": "b_assets",
        "B_liab": "b_liab",
        "b_liab": "b_liab",
        "B_total_equity": "b_total_equity",
        "b_total_equity": "b_total_equity",
        "B_fixed_assets": "b_fixed_assets",
        "b_fixed_assets": "b_fixed_assets",
        "B_cash_equivalents": "b_cash_equivalents",
        "b_cash_equivalents": "b_cash_equivalents",
        "B_shortterm_debt": "b_shortterm_debt",
        "b_shortterm_debt": "b_shortterm_debt",
        "B_longterm_debt": "b_longterm_debt",
        "b_longterm_debt": "b_longterm_debt",
        "PL_revenue": "pl_revenue",
        "pl_revenue": "pl_revenue",
        "PL_gross_profit": "pl_gross_profit",
        "pl_gross_profit": "pl_gross_profit",
        "PL_profit_from_sales": "pl_profit_from_sales",
        "pl_profit_from_sales": "pl_profit_from_sales",
        "PL_net_profit": "pl_net_profit",
        "pl_net_profit": "pl_net_profit",
        "PL_cost_of_sales": "pl_cost_of_sales",
        "pl_cost_of_sales": "pl_cost_of_sales",
        "CF_balance": "cf_balance",
        "cf_balance": "cf_balance",
        "CF_balance_operating": "cf_balance_operating",
        "cf_balance_operating": "cf_balance_operating",
        "simplified": "simplified",
        "outlier": "outlier",
    }

    record: dict[str, Any] = {}
    for csv_field, api_field in field_map.items():
        if csv_field in row:
            if api_field in _STRING_FIELDS:
                # Строковые поля: всегда строка, без конвертации в число
                val = row[csv_field]
                if val is not None:
                    val = str(val).strip()
                    if val and val.lower() not in ("nan", "none", "null", ""):
                        record[api_field] = val
            else:
                val = _clean_value(row[csv_field])
                if val is not None:
                    record[api_field] = val

    return record


def read_csv_records(csv_path: str) -> list[dict]:
    """Читает CSV файл и возвращает список записей для API."""
    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = _csv_row_to_record(row)
            if record.get("inn"):  # Пропускаем записи без ИНН
                records.append(record)
    return records


def send_batch(
    client: httpx.Client,
    base_url: str,
    token: str,
    records: list[dict],
    year: int,
) -> dict:
    """Отправляет батч записей на API."""
    payload = {
        "records": records,
        "year": year,
    }
    resp = client.post(
        f"{base_url}/ingest-rfsd/batch",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=300.0,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(
        description="Загрузка данных RFSD из CSV через API backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--csv-path",
        default=str(Path(__file__).resolve().parent.parent / "data" / "RFSD_2023-2025_final.csv"),
        help="Путь к CSV файлу (по умолчанию: data/RFSD_2023-2025_final.csv)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2025,
        help="Финансовый год по умолчанию (если не удаётся вычислить из данных, по умолчанию: 2025)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="URL backend API (по умолчанию: http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="JWT Bearer токен для авторизации (роль DATA_STEWARD или ADMIN)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Размер батча записей (по умолчанию: 50)",
    )
    parser.add_argument(
        "--batch",
        type=str,
        default=None,
        help="Номер конкретного батча или диапазон (например: 253, 253-260). 1-based нумерация",
    )
    parser.add_argument(
        "--list-batches",
        action="store_true",
        help="Показать структуру батчей и выйти",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=3,
        help="Количество попыток при HTTP 500 (по умолчанию: 3)",
    )

    args = parser.parse_args()

    # Проверка CSV файла
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"❌ CSV файл не найден: {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Проверка доступности backend
    print(f"🔍 Проверка доступности backend: {args.base_url}")
    try:
        with httpx.Client() as client:
            health = client.get(f"{args.base_url}/health", timeout=10.0)
            health.raise_for_status()
            print(f"✅ Backend доступен: {health.json()}")
    except httpx.ConnectError:
        print(f"❌ Backend недоступен: {args.base_url}", file=sys.stderr)
        print("   Убедитесь, что backend запущен (docker compose up fastapi)", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка проверки backend: {e}", file=sys.stderr)
        sys.exit(1)

    # Чтение CSV
    print(f"📂 Чтение CSV файла: {csv_path}")
    records = read_csv_records(str(csv_path))
    total = len(records)
    print(f"   Найдено записей: {total}")

    if total == 0:
        print("⚠️  Нет записей для загрузки", file=sys.stderr)
        sys.exit(0)

    # Разбивка на батчи
    batch_size = args.batch_size
    batches = [records[i : i + batch_size] for i in range(0, total, batch_size)]
    print(f"📦 Батчей: {len(batches)} (по {batch_size} записей)")

    # Определяем какие батчи обрабатывать
    total_batches = len(batches)

    if args.list_batches:
        print(f"\n📦 Структура батчей (batch-size={batch_size}):")
        print(f"   Всего записей: {total}")
        print(f"   Всего батчей:  {total_batches}")
        print()
        for idx, batch in enumerate(batches, start=1):
            first_inn = batch[0].get("inn", "?")
            last_inn = batch[-1].get("inn", "?")
            print(f"   Батч {idx:4d}: {len(batch):3d} записей (ИНН {first_inn} … {last_inn})")
        sys.exit(0)

    # Парсим --batch
    if args.batch is not None:
        batch_spec = args.batch.strip()
        if "-" in batch_spec:
            parts = batch_spec.split("-", 1)
            batch_start = int(parts[0])
            batch_end = int(parts[1])
        else:
            batch_start = int(batch_spec)
            batch_end = batch_start

        if batch_start < 1 or batch_end > total_batches or batch_start > batch_end:
            print(f"❌ Неверный диапазон батчей: {batch_spec} (допустимо: 1-{total_batches})", file=sys.stderr)
            sys.exit(1)

        selected_batches = list(range(batch_start, batch_end + 1))
        print(f"🎯 Выбранные батчи: {batch_start}–{batch_end} ({len(selected_batches)} батчей)")
    else:
        selected_batches = list(range(1, total_batches + 1))

    max_retry = args.retry

    # Загрузка
    total_companies = 0
    total_financials = 0
    total_chunks = 0
    all_errors: list[str] = []
    start_time = time.time()

    with httpx.Client() as client:
        for batch_idx in selected_batches:
            batch = batches[batch_idx - 1]  # 0-based index

            print(f"\n⏳ Батч {batch_idx}/{total_batches} ({len(batch)} записей)...")

            # Retry loop for HTTP 500 errors
            success = False
            for attempt in range(1, max_retry + 1):
                try:
                    result = send_batch(
                        client=client,
                        base_url=args.base_url,
                        token=args.token,
                        records=batch,
                        year=args.year,
                    )

                    total_companies += result.get("companies_indexed", 0)
                    total_financials += result.get("financials_indexed", 0)
                    total_chunks += result.get("chunks_indexed", 0)
                    batch_errors = result.get("errors", [])
                    all_errors.extend(batch_errors)

                    print(f"   ✅ Компаний: {result.get('companies_indexed', 0)}, "
                          f"Финансов: {result.get('financials_indexed', 0)}, "
                          f"Чанков: {result.get('chunks_indexed', 0)}")
                    if batch_errors:
                        print(f"   ⚠️  Ошибок в батче: {len(batch_errors)}")
                    success = True
                    break

                except httpx.HTTPStatusError as e:
                    error_detail = ""
                    try:
                        error_detail = e.response.json().get("detail", "")
                    except Exception:
                        error_detail = e.response.text
                    print(f"   ❌ HTTP ошибка {e.response.status_code}: {error_detail}", file=sys.stderr)

                    if e.response.status_code == 401:
                        print("   Токен истёк или невалиден. Получите новый токен.", file=sys.stderr)
                        sys.exit(1)
                    elif e.response.status_code == 403:
                        print("   Недостаточно прав. Нужна роль DATA_STEWARD или ADMIN.", file=sys.stderr)
                        sys.exit(1)
                    elif e.response.status_code >= 500:
                        if attempt < max_retry:
                            wait = 5 * attempt
                            print(f"   ⏳ Попытка {attempt}/{max_retry}, жду {wait}с...", file=sys.stderr)
                            time.sleep(wait)
                        else:
                            print(f"   ❌ Все {max_retry} попытки исчерпаны для батча {batch_idx}", file=sys.stderr)

                except httpx.ConnectError:
                    print(f"   ❌ Потеряно соединение с backend", file=sys.stderr)
                    if attempt < max_retry:
                        time.sleep(5 * attempt)
                    else:
                        sys.exit(1)

                except Exception as e:
                    print(f"   ❌ Неожиданная ошибка: {e}", file=sys.stderr)
                    if attempt < max_retry:
                        time.sleep(5 * attempt)
                    else:
                        all_errors.append(f"Batch {batch_idx}: {e}")

            if not success:
                print(f"   ⏭️  Пропускаю батч {batch_idx}, продолжаю...", file=sys.stderr)

    # Итоги
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("📊 ИТОГИ ЗАГРУЗКИ")
    print("=" * 60)
    print(f"   Время:               {elapsed:.1f} сек")
    print(f"   Батчи:               {selected_batches[0]}–{selected_batches[-1]} из {total_batches}")
    print(f"   Компаний загружено:  {total_companies}")
    print(f"   Финансов загружено:  {total_financials}")
    print(f"   Чанков создано:      {total_chunks}")
    print(f"   Ошибок:              {len(all_errors)}")

    if all_errors:
        print(f"\n⚠️  Первые ошибки (макс. 10):")
        for err in all_errors[:10]:
            print(f"   - {err}")

    if total_companies > 0:
        print(f"\n✅ Загрузка завершена успешно!")
    else:
        print(f"\n❌ Не удалось загрузить данные. Проверьте ошибки выше.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
