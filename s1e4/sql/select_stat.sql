select status, created_ts from logs
where
    dev_id = ?
    and created_ts between ? and ?
ordered by created_ts asc;