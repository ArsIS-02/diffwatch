# DiffWatch

Ежедневные снапшоты состояния хоста — дешёвый аналог FIM (File/Host Integrity
Monitoring). Любое изменение относительно предыдущего снапшота уходит событием
в Graylog (GELF UDP). Только Python stdlib, работает от обычного пользователя.

## Что снимает

| Категория | Источник | Ключевой детект |
|---|---|---|
| Открытые порты | `ss -tulnH` | новый LISTEN — кто-то поднял сервис |
| systemd-юниты | `systemctl list-unit-files --state=enabled` (system + user) | persistence через автозагрузку |
| Crontab | `/etc/crontab`, `/etc/cron.d/*`, `/var/spool/cron/*`, `crontab -l` (хеш содержимого) | persistence через расписания |
| Пакеты | `rpm -qa` | установка/удаление софта |

События: `dw_event=added|removed|changed`, `dw_kind=port|unit|cron|package`,
`dw_item`, `dw_detail`. Плюс ежедневный пульс `dw_event=snapshot` со счётчиками —
по нему удобно следить, что сам DiffWatch жив.

## Установка (RED OS 8, пользователь redos)

```bash
mkdir -p ~/diffwatch ~/.local/share/diffwatch
cp diffwatch.py ~/diffwatch/
cp systemd/diffwatch.service systemd/diffwatch.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now diffwatch.timer
```

По умолчанию шлёт на `127.0.0.1:12206` (вход Graylog «Homelab tools»).
Переопределения — через `DW_GELF_HOST`, `DW_GELF_PORT` в Environment юнита.
Для чтения `/var/spool/cron` задайте `DW_SUDO_PASS` в `~/.config/systemd/user/diffwatch.service.d/override.conf`
(файл не коммитить).

Первый запуск создаёт базовый снапшот без событий; изменения считаются со
второго прогона. Ручной запуск: `systemctl --user start diffwatch.service`.

## Graylog

Поток **DiffWatch** (правило `homelab_app=diffwatch`). Правила-алерты:
«DIFFWATCH - Новый открытый порт» (высокий), «DIFFWATCH - Изменение
автозагрузки» (высокий), «DIFFWATCH - Изменение состава пакетов» (средний).

## Тесты

```bash
python -m pytest tests/ -v
```
