# Importing Content

AssistantMD imports vault files and public HTTP/HTTPS URLs into Markdown files.
Imports can be submitted from chat, Monty workflows, or the Dashboard Import
section. All surfaces use the same durable ingestion job queue.

## Monitor and control imports

Open **Dashboard > Import** to see recent jobs across vaults. The Import Status
table shows queued, processing, completed, failed, and cancelled jobs, along
with their outputs or errors.

- Use **Refresh Import Status** to reload the durable job list.
- Use **Process Queue Now** to request an immediate run of the scheduled
  ingestion worker. The run still observes the configured batch size.
- Queued jobs can be cancelled. A processing job cannot be cancelled because
  its extraction thread or external OCR request may already be running.

The table refreshes automatically while queued or processing jobs are present.

## Tune queue timing

Two editable settings control scheduled imports:

- `ingestion_worker_interval_seconds` controls how often the worker checks for
  queued jobs. A shorter interval reduces pickup latency.
- `ingestion_worker_batch_size` controls how many jobs a worker run processes
  concurrently. A batch larger than this value requires multiple worker runs.

For interactive agent-driven research, use a shorter interval or the
**Process Queue Now** action when you want prompt pickup. For background import
work, a longer interval reduces scheduling activity. Increasing batch size can
improve throughput, but it also increases simultaneous network, OCR, CPU, and
external API usage.

Scheduled worker runs do not overlap. Slow imports can therefore extend the
effective wait for jobs left in the queue.

