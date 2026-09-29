export type ScheduledPost = {
  id: string;
  external_id: string;
  spreadsheet_id: string;
  worksheet: string;
  source_row: number | null;
  page_id: string | null;
  page_name: string | null;
  caption: string;
  image_url: string | null;
  scheduled_for_utc: string | null;
  source_timezone: string;
  status: string;
  attempt_count: number;
  facebook_post_id: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  writeback_error: string | null;
};

export type PublishingConfig = {
  configured: boolean;
  spreadsheet_id: string | null;
  worksheet: string | null;
  timezone: string | null;
  last_synced_at: string | null;
  last_sync_error: string | null;
  last_sync_result: { created: number; updated: number; unchanged: number; invalid: number } | null;
};
