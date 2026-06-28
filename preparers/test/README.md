# Test Preparer

Trivial passthrough-preparer для smoke-test и как шаблон для кастомных фреймворков.

## Что делает

`discover()` → все `*.md` файлы в `data/source/test/`
`transform()` → копирует как есть (никаких трансформаций)
`run(execute=True)` → атомарно публикует в `data/prepared/test/` через staging-rename

## Использование

```bash
# Dry-run
uv run python -m preparers.cli --framework test

# Apply
uv run python -m preparers.cli --framework test --execute
```

## Как добавить свой фреймворк

1. Создай `data/source/<myframework>/` с `.md` файлами.
2. Скопируй `preparers/test/prepare.py` в `preparers/<myframework>/`.
3. Замени класс `TestPreparer` на свой (если нужна трансформация) или оставь как есть (если passthrough).
4. Зарегистрируй пакет в `preparers/registry.py` (`_PREPARER_PACKAGES`).
5. Запусти `uv run python -m preparers.cli --framework <myframework> --execute`.