CREATE TRIGGER observations_no_update BEFORE UPDATE ON observations
BEGIN
  SELECT RAISE(ABORT, 'observations are immutable');
END;

CREATE TRIGGER observations_no_delete BEFORE DELETE ON observations
BEGIN
  SELECT RAISE(ABORT, 'observations are immutable');
END;
