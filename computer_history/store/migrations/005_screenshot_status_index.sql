CREATE INDEX observations_screenshot_status ON observations (
  source,
  json_extract(payload, '$.status'),
  started_at,
  json_extract(payload, '$.image_bytes')
) WHERE source = 'screenshot';
