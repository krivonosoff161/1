# Дедупликация документации (aggressive pass)

Дата: 2026-02-21

## Параметры прогона
- Mode: `aggressive`
- Similarity threshold: `0.89`
- Min shared filename tokens: `1`
- Max size ratio: `1.55`

## Результат
- Before docs files: `1426`
- After docs files: `1423`
- Candidate pairs checked: `27662`
- Similar pairs: `3`
- Near groups: `3`
- Moved near duplicates: `3`
- Exact duplicates moved: `0`

## Манифест
- `docs/archive/deduplicated/manifest_2026-02-21_07-15-27_aggressive.json`
- `docs/archive/deduplicated/manifest_2026-02-21_07-15-27_aggressive.md`

## Куда перенесены неканонические версии
- `docs/archive/deduplicated/near/`

## Примечание
- Канонические документы сохранены.
- Все спорные/похожие версии оставлены в архиве, удалений без следа нет.
