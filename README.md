# Keji 客迹

<p align="center">
  <b>Self-hosted client-work records for relationship-driven professional services.</b>
</p>

<p align="center">
  <a href="README.en.md">English overview</a> · <a href="README.zh-CN.md">中文完整文档</a>
</p>

<p align="center">
  <img src="docs/overview.svg" alt="Keji private client-work system overview" width="96%">
</p>

Keji is a private, self-hosted client-work operating system for insurance agents, independent advisors, and other professionals who need to preserve long-running customer context without scattering records across chat history, spreadsheets, and photo folders.

| Core surface | What Keji keeps explicit |
| --- | --- |
| Client graph | profiles, family/referral relationships, deduplication, relationship views |
| Work history | meetings, calls, follow-ups, tasks, reminders, and a unified timeline |
| Files / evidence | validated uploads, EXIF, thumbnails, SHA-256 deduplication, staged deletion |
| Insurance workflow | policy state/history, premium schedules, claims, material checklists, exports |
| Reliability | permission bits, audit history, backup/restore, documented deployment boundaries |

**Stack:** Django 5.2 · PostgreSQL 17 · HTMX · Alpine.js · Tailwind CSS · Pillow · Playwright · Docker Compose

For technical reviewers, start with the concise [English overview](README.en.md). For the complete feature matrix, deployment runbook, data model, backup/restore process, screenshots, and operational documentation, use the [Chinese documentation](README.zh-CN.md).

> Keji is an applied systems project. Its public value is end-to-end product ownership—domain modeling, privacy boundaries, document workflows, operational recovery, testing, and deployability—not a claim that it is part of my primary research agenda.

AGPL-3.0.