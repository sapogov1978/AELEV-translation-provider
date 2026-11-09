# Provenance

Репозиторий создан 2026-11-06 командой `git subtree split` из пути
`services/infrastructure/translator-service` исходного репозитория
`sapogov1978/AELEV`. Поэтому история provider-specific файлов до разделения
остаётся доступной через обычный `git log`.

Первоначальная реализация Index Translate появилась в split-history commit
`a131e818916e7e14de1985157d52cfab4f87ee6d`; дальнейшие исправления сохранены
в последующих subtree commits. Первый самостоятельный commit удаляет чужую
ответственность Translator и переименовывает provider-specific файлы, не
переписывая прежние commits.

Материалы сравнительного эксперимента перенесены без изменения содержания в
`docs/audit/model-selection/`. Они являются историческим evidence выбора, а не
активным runtime-контрактом. С 2026-11-09 активная поставка полностью
отказалась от standalone weights/runtime в пользу закреплённого remote API profile.
